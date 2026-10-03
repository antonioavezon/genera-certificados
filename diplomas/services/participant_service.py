"""Persistencia de la lista activa y de sus participantes."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import transaction

from diplomas.models import ImportBatch, ImportPhase, Participant
from diplomas.services.file_service import remove_stored
from diplomas.services.validation_service import ValidatedRow


def create_pending_from_upload(uploaded) -> ImportBatch:
    """Guarda la lista y deja las columnas listas para que la persona las asocie."""
    from django.conf import settings

    from diplomas.services.file_service import move_into_place, sha256_file, store_upload
    from diplomas.services.list_import_service import parse_list_file

    directory = Path(settings.UPLOADS_DIR) / "lists"
    temporary, original = store_upload(uploaded, directory)
    try:
        table = parse_list_file(temporary, original, max_rows=settings.MAX_LIST_ROWS)
        suffix = ".xlsx" if temporary.read_bytes()[:2] == b"PK" else ".csv"
        stored_name = move_into_place(temporary, directory, suffix)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    content_hash = sha256_file(directory / stored_name)
    with transaction.atomic():
        pending = get_pending_batch()
        if pending is not None:
            discard_pending(pending)
        batch = ImportBatch.objects.create(
            original_name=original,
            stored_name=stored_name,
            content_hash=content_hash,
            columns=table.headers,
            notes=" ".join(table.warnings),
            phase=ImportPhase.PENDING,
            total_rows=len(table.rows),
        )
    return batch


def revalidate_stored(batch: ImportBatch) -> None:
    """Vuelve a validar los participantes guardados y numera desde 1."""
    from diplomas.services.config_service import get_settings
    from diplomas.services.validation_service import validate_people

    people = list(batch.participants.order_by("row_number", "id"))
    for index, person in enumerate(people, start=1):
        if person.row_number != index:
            person.row_number = index
            person.save(update_fields=["row_number"])
    rows = validate_people(
        [(person.row_number, person.first_name, person.last_name, person.email) for person in people],
        require_last_name=get_settings().require_last_name,
    )
    by_number = {person.row_number: person for person in people}
    with transaction.atomic():
        for row in rows:
            person = by_number[row.row_number]
            person.first_name = row.first_name
            person.last_name = row.last_name
            person.email = row.email
            person.status = row.status
            person.observations = row.observations
            person.filename = row.filename
            person.duplicate_kind = row.duplicate_kind
            person.save()
        _refresh_counts(batch)
        batch.save()


def reload_active_rows(batch: ImportBatch):
    """Vuelve a leer el archivo original. Si ya no está, conserva lo importado."""
    from django.conf import settings

    from diplomas.services.list_import_service import parse_list_file
    from diplomas.services.validation_service import validate_table

    warnings: list[str] = []
    if not batch.stored_name or not batch.mapping:
        return warnings
    path = Path(settings.UPLOADS_DIR) / "lists" / batch.stored_name
    if not path.is_file():
        warnings.append(
            "No se encontró el archivo de lista original. Se usarán los registros ya importados."
        )
        return warnings
    table = parse_list_file(path, batch.original_name, max_rows=settings.MAX_LIST_ROWS)
    from diplomas.services.config_service import get_settings

    rows = validate_table(
        table.headers,
        table.rows,
        batch.mapping,
        require_last_name=get_settings().require_last_name,
    )
    resync(batch, rows, " ".join(table.warnings))
    return table.warnings


def get_active_batch() -> ImportBatch | None:
    return (
        ImportBatch.objects.filter(is_active=True, phase=ImportPhase.READY)
        .order_by("-created_at")
        .first()
    )


def get_pending_batch() -> ImportBatch | None:
    return ImportBatch.objects.filter(phase=ImportPhase.PENDING).order_by("-created_at").first()


def discard_pending(batch: ImportBatch | None = None) -> None:
    target = batch or get_pending_batch()
    if target is None or target.phase != ImportPhase.PENDING:
        return
    remove_stored(Path(settings.UPLOADS_DIR) / "lists", target.stored_name)
    target.delete()


def activate_mapping(batch: ImportBatch, mapping: dict[str, str], rows: list[ValidatedRow], notes: str) -> ImportBatch:
    with transaction.atomic():
        batch.mapping = mapping
        batch.notes = notes
        batch.phase = ImportPhase.READY
        batch.is_active = True
        _sync_participants(batch, rows)
        _refresh_counts(batch)
        batch.save()
        ImportBatch.objects.exclude(pk=batch.pk).update(is_active=False)
    return batch


def resync(batch: ImportBatch, rows: list[ValidatedRow], notes: str) -> None:
    with transaction.atomic():
        batch.notes = notes
        _sync_participants(batch, rows)
        _refresh_counts(batch)
        batch.save()


def _sync_participants(batch: ImportBatch, rows: list[ValidatedRow]) -> None:
    existing = {item.row_number: item for item in batch.participants.all()}
    seen: set[int] = set()
    for row in rows:
        seen.add(row.row_number)
        participant = existing.get(row.row_number)
        fields = {
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
            "status": row.status,
            "observations": row.observations,
            "filename": row.filename,
            "duplicate_kind": row.duplicate_kind,
        }
        if participant is None:
            Participant.objects.create(import_batch=batch, row_number=row.row_number, **fields)
            continue
        for name, value in fields.items():
            setattr(participant, name, value)
        participant.save()
    for row_number, participant in existing.items():
        if row_number in seen:
            continue
        if participant.generation_records.exists() or participant.email_deliveries.exists():
            participant.status = "error"
            participant.observations = "La fila ya no está en la lista. Se conservó por el historial."
            participant.save()
        else:
            participant.delete()


def _refresh_counts(batch: ImportBatch) -> None:
    participants = list(batch.participants.all())
    batch.total_rows = len(participants)
    batch.valid_count = sum(1 for item in participants if item.status == "valid")
    batch.warning_count = sum(1 for item in participants if item.status == "warning")
    batch.error_count = sum(1 for item in participants if item.status == "error")

