"""Carga de plantillas JPG, PNG y PDF, y conversión a una imagen RGB."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from diplomas.exceptions import CorruptFileError, InvalidTemplateError
from diplomas.models import TemplateConfiguration
from diplomas.services.file_service import (
    browser_filename,
    move_into_place,
    remove_stored,
    sha256_file,
    store_upload,
)
from diplomas.services.logging_service import get_logger

logger = get_logger("app")

Image.MAX_IMAGE_PIXELS = 150_000_000


def templates_dir() -> Path:
    return Path(settings.UPLOADS_DIR) / "templates"


def get_active_template() -> TemplateConfiguration | None:
    return (
        TemplateConfiguration.objects.filter(is_active=True)
        .order_by("-created_at")
        .first()
    )


def get_page_selection_template() -> TemplateConfiguration | None:
    latest = TemplateConfiguration.objects.order_by("-created_at").first()
    if latest is not None and latest.needs_page_selection:
        return latest
    return None


def import_upload(uploaded: UploadedFile, *, dpi: int) -> TemplateConfiguration:
    temporary, original = store_upload(uploaded, templates_dir())
    try:
        kind = _detect_kind(temporary, original)
        if kind == "pdf":
            page_count = _pdf_page_count(temporary)
            suffix = ".pdf"
        else:
            _load_image(temporary)
            page_count = 1
            suffix = f".{kind}"
        stored_name = move_into_place(temporary, templates_dir(), suffix)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    content_hash = sha256_file(templates_dir() / stored_name)
    selected = 1 if page_count == 1 else None
    width, height = (0, 0)
    if selected:
        try:
            width, height = _measure(templates_dir() / stored_name, kind, selected, dpi)
        except Exception:
            remove_stored(templates_dir(), stored_name)
            raise

    with transaction.atomic():
        template = TemplateConfiguration.objects.create(
            original_name=original,
            stored_name=stored_name,
            kind=kind,
            page_count=page_count,
            selected_page=selected,
            width_px=width,
            height_px=height,
            content_hash=content_hash,
            is_active=selected is not None,
        )
        if template.is_active:
            TemplateConfiguration.objects.exclude(pk=template.pk).update(is_active=False)
    return template


def select_page(template: TemplateConfiguration, page: int, *, dpi: int) -> TemplateConfiguration:
    if template.kind != "pdf":
        raise InvalidTemplateError("La plantilla actual no es un PDF de varias páginas.")
    if page < 1 or page > template.page_count:
        raise InvalidTemplateError(
            f"El PDF contiene {template.page_count} páginas. Seleccione una página entre 1 y {template.page_count}."
        )
    width, height = _measure(template_path(template), "pdf", page, dpi)
    with transaction.atomic():
        template.selected_page = page
        template.width_px = width
        template.height_px = height
        template.is_active = True
        template.save()
        TemplateConfiguration.objects.exclude(pk=template.pk).update(is_active=False)
    return template


def load_rgb(template: TemplateConfiguration, dpi: int) -> Image.Image:
    if not template.selected_page:
        raise InvalidTemplateError(
            f"El PDF contiene {template.page_count} páginas. Seleccione la página que desea utilizar."
        )
    path = template_path(template)
    if not path.is_file():
        raise InvalidTemplateError("No es posible leer la plantilla. El archivo ya no está disponible.")
    if template.kind == "pdf":
        image = _render_pdf_page(path, template.selected_page, dpi)
    else:
        image = _load_image(path)
    if image.width != template.width_px or image.height != template.height_px:
        template.width_px = image.width
        template.height_px = image.height
        template.save(update_fields=["width_px", "height_px"])
    return image


def template_path(template: TemplateConfiguration) -> Path:
    return templates_dir() / template.stored_name


def fit_thumbnail_size(width: int, height: int, max_edge: int = 480) -> tuple[int, int]:
    """Escala que usan las miniaturas de inicio para verse del mismo tamaño."""
    if width < 1 or height < 1:
        return (max_edge, round(max_edge * 370 / 480))
    scale = min(max_edge / width, max_edge / height, 1.0)
    return (max(1, round(width * scale)), max(1, round(height * scale)))


def thumbnail_png(template: TemplateConfiguration, max_edge: int = 480) -> bytes:
    """Devuelve una miniatura PNG de la plantilla, sin el texto del diploma."""
    if not template.selected_page:
        raise InvalidTemplateError(
            f"El PDF contiene {template.page_count} páginas. Seleccione la página que desea utilizar."
        )
    path = template_path(template)
    if not path.is_file():
        raise InvalidTemplateError("No es posible leer la plantilla. El archivo ya no está disponible.")
    if template.kind == "pdf":
        image = _render_pdf_page(path, template.selected_page, 72)
    else:
        image = _load_image(path)
    target = fit_thumbnail_size(image.width, image.height, max_edge)
    if image.size != target:
        image = image.resize(target, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _detect_kind(path: Path, original_name: str) -> str:
    data = path.read_bytes()[:16]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"%PDF-"):
        return "pdf"
    suffix = Path(browser_filename(original_name)).suffix.lower()
    if suffix == ".pdf":
        raise CorruptFileError("No es posible leer la plantilla PDF.")
    raise InvalidTemplateError(
        "La plantilla debe ser una imagen JPG o PNG, o un PDF. El archivo no tiene un formato compatible."
    )


def _pdf_page_count(path: Path) -> int:
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        logger.info("PDF de plantilla rechazado: %s", exc)
        raise CorruptFileError("No es posible leer la plantilla PDF.") from exc
    try:
        if document.is_encrypted and document.needs_pass:
            raise InvalidTemplateError(
                "El PDF está protegido con contraseña y no se puede usar como plantilla."
            )
        if document.page_count < 1:
            raise CorruptFileError("No es posible leer la plantilla PDF.")
        return document.page_count
    finally:
        document.close()


def _render_pdf_page(path: Path, page_number: int, dpi: int) -> Image.Image:
    zoom = max(dpi, 72) / 72
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        logger.info("No se pudo abrir el PDF de plantilla: %s", exc)
        raise CorruptFileError("No es posible leer la plantilla PDF.") from exc
    try:
        if page_number < 1 or page_number > document.page_count:
            raise InvalidTemplateError(
                f"El PDF contiene {document.page_count} páginas. Seleccione la página que desea utilizar."
            )
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        if pixmap.n != 3:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except (InvalidTemplateError, CorruptFileError):
        raise
    except Exception as exc:
        logger.exception("Fallo al rasterizar la plantilla PDF")
        raise CorruptFileError("No es posible leer la plantilla PDF.") from exc
    finally:
        document.close()
    return image


def _load_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as probe:
            probe.verify()
        with Image.open(path) as opened:
            opened.load()
            image = opened.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        logger.info("Imagen de plantilla rechazada: %s", exc)
        raise CorruptFileError(
            "No es posible leer la imagen. El archivo está dañado o no es un formato compatible."
        ) from exc
    return _to_rgb(image)


def _measure(path: Path, kind: str, page: int, dpi: int) -> tuple[int, int]:
    if kind == "pdf":
        image = _render_pdf_page(path, page, dpi)
    else:
        image = _load_image(path)
    return image.width, image.height


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.getchannel("A")
        background.paste(image.convert("RGBA"), mask=alpha)
        return background
    return image.convert("RGB")


def delete_template_file(template: TemplateConfiguration) -> None:
    remove_stored(templates_dir(), template.stored_name)
