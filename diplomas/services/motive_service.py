"""Lectura, edición y restauración del motivo del diploma."""

from __future__ import annotations

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from diplomas.exceptions import InvalidMotiveError
from diplomas.models import Motive
from diplomas.services.file_service import browser_filename, sha256_text, store_upload
from diplomas.services.logging_service import get_logger

logger = get_logger("app")
_MAX_CHARS = 5000
_MAX_LINES = 40


def get_motive() -> Motive:
    motive, _created = Motive.objects.get_or_create(pk=1)
    return motive


@transaction.atomic
def save_text(text: str) -> Motive:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    _validate_text(cleaned)
    motive = get_motive()
    if motive.text != cleaned:
        motive.previous_text = motive.text
    motive.text = cleaned
    motive.content_hash = sha256_text(cleaned)
    motive.save()
    return motive


@transaction.atomic
def restore_previous() -> Motive:
    motive = get_motive()
    if not motive.previous_text.strip():
        raise InvalidMotiveError("No hay una versión anterior para restaurar.")
    current = motive.text
    motive.text = motive.previous_text
    motive.previous_text = current
    motive.content_hash = sha256_text(motive.text)
    motive.save()
    return motive


def import_txt(uploaded: UploadedFile) -> Motive:
    original = browser_filename(uploaded.name)
    if Path_suffix(original) not in {".txt", ""}:
        raise InvalidMotiveError("El motivo debe cargarse desde un archivo de texto .txt.")
    from django.conf import settings

    temporary, _original = store_upload(uploaded, settings.TEMP_DIR)
    try:
        data = temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)
    if b"\x00" in data:
        raise InvalidMotiveError(
            "No se pudo leer el motivo. El archivo no es un texto UTF-8 válido."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        logger.info("Motivo con codificación no válida")
        raise InvalidMotiveError(
            "No se pudo leer el motivo. Guarde el archivo como UTF-8 e intente de nuevo."
        ) from exc
    return save_text(text)


def _validate_text(text: str) -> None:
    if len(text) > _MAX_CHARS:
        raise InvalidMotiveError(f"El motivo supera el máximo de {_MAX_CHARS} caracteres.")
    if text.strip() and len(text.splitlines()) > _MAX_LINES:
        raise InvalidMotiveError(f"El motivo supera el máximo de {_MAX_LINES} líneas.")


def Path_suffix(name: str) -> str:
    from pathlib import Path

    return Path(name).suffix.lower()
