"""Escritura atómica del PDF final a partir de la imagen ya renderizada."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pymupdf
from django.conf import settings
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from diplomas.exceptions import GenerationError, StoragePermissionError
from diplomas.services.logging_service import get_logger

logger = get_logger("generation")


def write_pdf_atomic(image: Image.Image, destination: Path, *, dpi: int, title: str) -> None:
    """Genera un temporal, lo verifica y solo entonces lo mueve al nombre definitivo."""
    if dpi < 72:
        raise GenerationError("La resolución configurada no es válida para crear el PDF.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(settings.TEMP_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temporary = temp_dir / f"{uuid.uuid4().hex}.pdf"
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    try:
        _write_pdf(rgb, temporary, dpi=dpi, title=title)
        _assert_pdf_valid(temporary)
        os.replace(temporary, destination)
    except StoragePermissionError:
        raise
    except GenerationError:
        raise
    except OSError as exc:
        logger.exception("No se pudo escribir el PDF %s", destination.name)
        raise StoragePermissionError(
            "No es posible escribir en la carpeta de diplomas. Revise los permisos de la carpeta."
        ) from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                logger.warning("No se pudo eliminar el PDF temporal %s", temporary.name, exc_info=True)


def _write_pdf(image: Image.Image, path: Path, *, dpi: int, title: str) -> None:
    width_pt = image.width * 72.0 / dpi
    height_pt = image.height * 72.0 / dpi
    document = canvas.Canvas(str(path), pagesize=(width_pt, height_pt))
    document.setTitle(title or "Diploma")
    document.setAuthor("Sistema de Generación de Diplomas")
    document.drawImage(
        ImageReader(image),
        0,
        0,
        width=width_pt,
        height=height_pt,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )
    document.showPage()
    document.save()


def _assert_pdf_valid(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 500:
        raise GenerationError("El PDF generado está incompleto y no se guardó.")
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        logger.exception("El PDF temporal no se pudo abrir")
        raise GenerationError("El PDF generado está incompleto y no se guardó.") from exc
    try:
        if document.page_count < 1:
            raise GenerationError("El PDF generado está incompleto y no se guardó.")
    finally:
        document.close()
