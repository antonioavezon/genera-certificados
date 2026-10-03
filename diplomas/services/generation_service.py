"""Preflight y generación participante por participante."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from diplomas.exceptions import DiplomaError, GenerationError, StoragePermissionError
from diplomas.models import (
    BatchStatus,
    GenerationBatch,
    GenerationRecord,
    GenerationStatus,
    OverflowPolicy,
)
from diplomas.services.config_service import configuration_problems, get_settings, snapshot, snapshot_hash
from diplomas.services.email.email_service import EmailService
from diplomas.services.file_service import assert_writable, disk_space_problem, ensure_directories
from diplomas.services.filename_service import assign_filenames
from diplomas.services.logging_service import get_logger
from diplomas.services.motive_service import get_motive
from diplomas.services.participant_service import get_active_batch, revalidate_stored
from diplomas.services.pdf_service import write_pdf_atomic
from diplomas.services.render_service import render_certificate
from diplomas.services.template_service import get_active_template, load_rgb

logger = get_logger("generation")


def _only(participants, only_id: int | None):
    if only_id is None:
        return participants
    return [person for person in participants if person.pk == only_id]


_READY_ACTIONS = {"generate", "regenerate", "already_exists"}


@dataclass
class PreflightReport:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generatable: int = 0
    existing_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.blockers


class GenerationService:
    def preflight(
        self,
        *,
        send_email: bool,
        regenerate: bool,
        numbered_copies: bool = False,
        only_id: int | None = None,
    ) -> PreflightReport:
        report = PreflightReport()
        report.blockers.extend(ensure_directories())
        output = Path(django_settings.DIPLOMAS_OUTPUT_DIR)
        try:
            assert_writable(output, label="la carpeta de diplomas")
        except StoragePermissionError as exc:
            report.blockers.append(exc.user_message)

        batch = get_active_batch()
        template = get_active_template()
        motive = get_motive()
        layout = get_settings()
        report.blockers.extend(configuration_problems(layout))

        if batch is None:
            report.blockers.append("Cargue y confirme una lista de participantes antes de generar.")
        if template is None or not template.is_ready:
            report.blockers.append("Cargue una plantilla válida antes de generar.")
        elif template.needs_page_selection:
            report.blockers.append(
                f"El PDF contiene {template.page_count} páginas. Seleccione la página que desea utilizar."
            )
        if not motive.is_ready:
            report.blockers.append("Escriba o cargue el motivo del diploma antes de generar.")
        if send_email:
            ready, problems = EmailService().provider_ready()
            if not ready:
                report.blockers.extend(problems)
            if batch is not None and not (batch.mapping or {}).get("email"):
                report.blockers.append(
                    "No se encontró una columna de correo electrónico. "
                    "Seleccione qué columna de la lista contiene el correo."
                )
        if report.blockers or batch is None:
            return report

        try:
            revalidate_stored(batch)
        except DiplomaError as exc:
            report.blockers.append(exc.user_message)
            return report
        batch.refresh_from_db()
        participants = _only(list(batch.participants.all()), only_id)
        if not participants:
            report.blockers.append("La lista no contiene participantes.")
            return report

        plans = assign_filenames(
            participants,
            output,
            policy=layout.collision_policy,
            regenerate=regenerate,
            numbered_copies=numbered_copies,
        )
        actionable = [plan for plan in plans.values() if plan.action in _READY_ACTIONS]
        if not actionable:
            report.blockers.append("No hay participantes válidos para generar.")
        report.generatable = sum(1 for plan in plans.values() if plan.action in {"generate", "regenerate"})
        blocked = [plan for plan in plans.values() if plan.action == "blocked"]
        existing = [plan for plan in plans.values() if plan.action == "already_exists"]
        report.existing_count = len(existing)
        if blocked:
            report.warnings.append(
                f"{len(blocked)} registro(s) producen un archivo repetido y se bloquearán. "
                "Puede revisar la lista o activar explícitamente la política de sufijos."
            )
        errors = sum(1 for item in participants if item.status == "error")
        if errors:
            report.warnings.append(f"{errors} registro(s) tienen errores y se omitirán.")
        required = max(report.generatable, 1) * 700_000
        space = disk_space_problem(output, required)
        if space and report.generatable:
            report.blockers.append(space)
        return report

    def run(
        self,
        *,
        send_email: bool,
        regenerate: bool,
        numbered_copies: bool = False,
        only_id: int | None = None,
    ) -> GenerationBatch:
        report = self.preflight(
            send_email=send_email,
            regenerate=regenerate,
            numbered_copies=numbered_copies,
            only_id=only_id,
        )
        if not report.ok:
            raise GenerationError(report.blockers[0])

        source = get_active_batch()
        template = get_active_template()
        motive = get_motive()
        layout = get_settings()
        if source is None or template is None:
            raise GenerationError("Faltan datos para generar. Revise la lista y la plantilla.")
        config = snapshot(layout)
        output = Path(django_settings.DIPLOMAS_OUTPUT_DIR)
        try:
            base_image = load_rgb(template, layout.dpi)
        except DiplomaError as exc:
            logger.exception("La plantilla no se pudo preparar")
            raise GenerationError(exc.user_message) from exc

        batch = GenerationBatch.objects.create(
            import_batch=source,
            template=template,
            list_hash=source.content_hash,
            template_hash=template.content_hash,
            motive_hash=motive.content_hash,
            motive_text=motive.text,
            config_hash=snapshot_hash(config),
            config_snapshot=config,
            total=1 if only_id else source.participants.count(),
            status=BatchStatus.RUNNING,
            regenerate=regenerate,
            send_email=send_email,
            message=" ".join(report.warnings),
        )
        interrupted = ""
        participants = _only(list(source.participants.all()), only_id)
        plans = assign_filenames(
            participants,
            output,
            policy=layout.collision_policy,
            regenerate=regenerate,
            numbered_copies=numbered_copies,
        )
        try:
            for participant in participants:
                plan = plans[participant.pk]
                try:
                    self._process_participant(
                        batch=batch,
                        participant=participant,
                        plan=plan,
                        base_image=base_image,
                        motive_text=motive.text,
                        layout=layout,
                        output=output,
                        regenerate=regenerate,
                    )
                except StoragePermissionError as exc:
                    interrupted = exc.user_message
                    logger.error(
                        exc.user_message,
                        extra={"batch": batch.pk, "participant": participant.full_name},
                    )
                    break
        except Exception:
            logger.exception("El lote se interrumpió", extra={"batch": batch.pk})
            interrupted = interrupted or (
                "El proceso se interrumpió. Los diplomas ya guardados se conservan."
            )
        self._close_batch(batch, interrupted=interrupted)
        if send_email:
            email_result = EmailService().send_for_batch(batch)
            note = email_result.summary
            if email_result.stopped_reason:
                note = f"{note} {email_result.stopped_reason}"
            batch.message = f"{batch.message} {note}".strip()
            batch.save(update_fields=["message"])
        return batch

    def _process_participant(
        self,
        *,
        batch,
        participant,
        plan,
        base_image,
        motive_text,
        layout,
        output: Path,
        regenerate: bool,
    ) -> None:
        extra = {"batch": batch.pk, "participant": participant.full_name}
        if plan.action == "skip":
            self._record(batch, participant, plan.filename, GenerationStatus.SKIPPED, plan.message)
            logger.info("Omitido: %s", plan.message, extra=extra)
            return
        if plan.action == "blocked":
            self._record(batch, participant, plan.filename, GenerationStatus.FAILED, plan.message)
            logger.info("Conflicto de archivo: %s", plan.message, extra=extra)
            return

        destination = output / plan.filename
        if destination.exists() and not regenerate:
            message = f"El diploma {plan.filename} ya existe y fue omitido."
            self._record(batch, participant, plan.filename, GenerationStatus.ALREADY_EXISTS, message)
            logger.info(message, extra=extra)
            return

        try:
            rendered = render_certificate(base_image.copy(), participant.full_name, motive_text, layout)
            if not rendered.name_fits and layout.name_overflow_policy == OverflowPolicy.BLOCK:
                self._record(
                    batch,
                    participant,
                    plan.filename,
                    GenerationStatus.FAILED,
                    "Conflicto: el nombre no cabe en el ancho disponible ni con el tamaño mínimo. "
                    "No se generó el diploma.",
                )
                return
            if destination.exists() and not regenerate:
                message = f"El diploma {plan.filename} ya existe y fue omitido."
                self._record(batch, participant, plan.filename, GenerationStatus.ALREADY_EXISTS, message)
                return
            write_pdf_atomic(
                rendered.image,
                destination,
                dpi=layout.dpi,
                title=participant.full_name or plan.filename,
            )
        except StoragePermissionError:
            raise
        except DiplomaError as exc:
            logger.warning(exc.user_message, extra=extra)
            self._record(batch, participant, plan.filename, GenerationStatus.FAILED, exc.user_message)
            return
        except Exception:
            logger.exception("Fallo al generar un diploma", extra=extra)
            self._record(
                batch,
                participant,
                plan.filename,
                GenerationStatus.FAILED,
                "No fue posible generar este diploma. El detalle quedó en el registro técnico.",
            )
            return

        status = (
            GenerationStatus.REGENERATED
            if plan.action == "regenerate"
            else GenerationStatus.GENERATED
        )
        parts = [plan.message, *rendered.warnings]
        message = " ".join(part for part in parts if part).strip()
        self._record(batch, participant, plan.filename, status, message)
        logger.info("Generado %s", plan.filename, extra=extra)

    def _record(self, batch, participant, filename: str, status: str, message: str) -> None:
        with transaction.atomic():
            GenerationRecord.objects.create(
                batch=batch,
                participant=participant,
                first_name=participant.first_name,
                last_name=participant.last_name,
                email=participant.email,
                email_key=participant.email_key,
                filename=filename,
                status=status,
                message=message,
                config_hash=batch.config_hash,
            )

    def _close_batch(self, batch: GenerationBatch, *, interrupted: str) -> None:
        records = batch.records.all()
        batch.generated_count = records.filter(
            status__in=[GenerationStatus.GENERATED, GenerationStatus.REGENERATED]
        ).count()
        batch.already_exists_count = records.filter(status=GenerationStatus.ALREADY_EXISTS).count()
        batch.skipped_count = records.filter(status=GenerationStatus.SKIPPED).count()
        batch.error_count = records.filter(status=GenerationStatus.FAILED).count()
        batch.finished_at = timezone.now()
        if interrupted:
            batch.status = BatchStatus.INTERRUPTED
            batch.message = f"{batch.message} {interrupted}".strip()
        else:
            batch.status = BatchStatus.COMPLETED
        batch.save()
