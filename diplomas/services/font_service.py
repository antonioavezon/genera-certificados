"""Fuentes TTF y OTF de la carpeta fonts, sin depender de una ruta del sistema."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from PIL import ImageFont

from diplomas.exceptions import FontNotFoundError

_STYLE_SUFFIXES = (
    "-BoldOblique",
    "-BoldItalic",
    "-Bold",
    "-Oblique",
    "-Italic",
    "-Regular",
)


def fonts_directory() -> Path:
    return Path(settings.FONTS_DIR)


def available_fonts() -> list[str]:
    directory = fonts_directory()
    if not directory.exists():
        return []
    names = [
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".ttf", ".otf"}
    ]
    return sorted(names, key=str.casefold)


def font_exists(name: str) -> bool:
    if not name or Path(name).name != name:
        return False
    path = fonts_directory() / name
    return path.is_file() and path.suffix.lower() in {".ttf", ".otf"}


def resolve_font_file(selected: str, *, bold: bool = False, italic: bool = False) -> Path:
    if not font_exists(selected):
        raise FontNotFoundError("La fuente seleccionada no está disponible.")
    if not bold and not italic:
        return fonts_directory() / selected

    root = Path(selected).stem
    extension = Path(selected).suffix
    for suffix in _STYLE_SUFFIXES:
        if root.endswith(suffix):
            root = root[: -len(suffix)]
            break

    if bold and italic:
        variants = (f"{root}-BoldOblique", f"{root}-BoldItalic")
    elif bold:
        variants = (f"{root}-Bold",)
    else:
        variants = (f"{root}-Oblique", f"{root}-Italic")

    directory = fonts_directory()
    for variant in variants:
        for ext in {extension, ".ttf", ".otf"}:
            candidate = directory / f"{variant}{ext}"
            if candidate.is_file():
                return candidate
    return directory / selected


def load_font(selected: str, size_px: int, *, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    path = resolve_font_file(selected, bold=bold, italic=italic)
    try:
        return ImageFont.truetype(str(path), size=max(1, size_px))
    except OSError as exc:
        raise FontNotFoundError("La fuente seleccionada no está disponible.") from exc
