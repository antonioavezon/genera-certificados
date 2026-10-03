"""Nombres de archivo seguros, independientes del sistema operativo."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from diplomas.exceptions import DiplomaError

_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_SAFE_PDF = re.compile(r"[a-z0-9][a-z0-9._-]*\.pdf")


@dataclass(frozen=True)
class FilenamePlan:
    participant_id: int
    filename: str
    action: str
    message: str


def slug_part(value: str) -> str:
    """Convierte un texto visible en un fragmento seguro de nombre de archivo."""
    text = value.replace("ñ", "n").replace("Ñ", "N")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text


def preferred_filename(first_name: str, last_name: str) -> tuple[str, str]:
    """Devuelve el nombre preferente y una advertencia si hubo que acortarlo."""
    first = slug_part(first_name) or "sin-nombre"
    last = slug_part(last_name)
    if first in _RESERVED:
        first = f"{first}-archivo"
    if last in _RESERVED:
        last = f"{last}-archivo"
    filename = f"{first}.{last}.pdf" if last else f"{first}.pdf"
    warning = ""
    if len(filename) > 120:
        stem = filename[:-4][:116].rstrip(".-_")
        filename = f"{stem}.pdf"
        warning = "El nombre de archivo se acortó porque era demasiado largo."
    return assert_safe_pdf_name(filename), warning


def with_suffix(filename: str, number: int) -> str:
    stem = filename[:-4]
    return assert_safe_pdf_name(f"{stem}_{number}.pdf")


def assert_safe_pdf_name(filename: str) -> str:
    if not _SAFE_PDF.fullmatch(filename):
        raise DiplomaError("El nombre de archivo del diploma no es válido.")
    return filename


def assign_filenames(
    participants,
    output_dir: Path,
    *,
    policy: str,
    regenerate: bool,
    numbered_copies: bool = False,
) -> dict[int, FilenamePlan]:
    """Reparte nombres sin sobrescribir y sin resolver colisiones en silencio."""
    existing = set()
    if output_dir.exists():
        existing = {path.name.casefold() for path in output_dir.glob("*.pdf")}
    used: set[str] = set()
    plans: dict[int, FilenamePlan] = {}
    ordered = sorted(participants, key=lambda item: (item.row_number, item.pk or 0))

    for participant in ordered:
        if participant.status == "error":
            plans[participant.pk] = FilenamePlan(
                participant.pk,
                participant.filename,
                "skip",
                participant.observations or "El registro tiene errores y fue omitido.",
            )
            continue

        preferred, shorten_warning = preferred_filename(participant.first_name, participant.last_name)
        if numbered_copies and preferred.casefold() in existing:
            candidate = _first_free_copy(preferred, used, existing)
            if candidate is None:
                plans[participant.pk] = FilenamePlan(
                    participant.pk,
                    preferred,
                    "blocked",
                    f"No quedó un nombre disponible a partir de {preferred} sin reemplazar el diploma existente.",
                )
                continue
            used.add(candidate.casefold())
            message = f"Se creó {candidate} sin reemplazar el diploma existente."
            if shorten_warning:
                message = f"{shorten_warning} {message}"
            plans[participant.pk] = FilenamePlan(participant.pk, candidate, "generate", message)
            continue

        candidate, collision_message = _claim(
            preferred,
            used=used,
            existing=existing,
            policy=policy,
            regenerate=regenerate,
        )
        if candidate is None:
            plans[participant.pk] = FilenamePlan(
                participant.pk,
                preferred,
                "blocked",
                collision_message,
            )
            continue

        used.add(candidate.casefold())
        action = "generate"
        message = shorten_warning
        if candidate.casefold() in existing and not regenerate:
            action = "already_exists"
            message = f"El diploma {candidate} ya existe y fue omitido."
        elif candidate.casefold() in existing and regenerate:
            action = "regenerate"
            message = f"Se regeneró el diploma {candidate} porque usted lo solicitó."
        elif candidate != preferred:
            message = f"El archivo preferente ya estaba asignado. Se utilizó {candidate}."
            if shorten_warning:
                message = f"{shorten_warning} {message}"
        plans[participant.pk] = FilenamePlan(participant.pk, candidate, action, message.strip())
    return plans


def _first_free_copy(preferred: str, used: set[str], existing: set[str]) -> str | None:
    """Busca nombre_1.pdf, nombre_2.pdf… sin tocar el archivo original."""
    for number in range(1, 500):
        candidate = with_suffix(preferred, number)
        key = candidate.casefold()
        if key in used or key in existing:
            continue
        return candidate
    return None


def _claim(
    preferred: str,
    *,
    used: set[str],
    existing: set[str],
    policy: str,
    regenerate: bool,
) -> tuple[str | None, str]:
    preferred_key = preferred.casefold()
    taken_in_batch = preferred_key in used
    if not taken_in_batch:
        return preferred, ""

    if policy != "suffix":
        return None, (
            f"Conflicto: hay otro participante que produce el mismo archivo {preferred}. "
            "Este registro se bloqueó para no sobrescribir."
        )

    for number in range(2, 500):
        candidate = with_suffix(preferred, number)
        key = candidate.casefold()
        if key in used:
            continue
        if key in existing and not regenerate:
            continue
        return candidate, ""
    return None, (
        f"Conflicto: no quedó un nombre disponible a partir de {preferred} "
        "sin sobrescribir un diploma existente."
    )
