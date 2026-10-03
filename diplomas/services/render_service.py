"""Dibujo del nombre y del motivo sobre la plantilla."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from diplomas.models import ApplicationSettings
from diplomas.services.font_service import load_font

_HEX = {
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
}


@dataclass
class RenderResult:
    image: Image.Image
    warnings: list[str]
    name_font_size: int
    motive_font_size: int
    rendered_name: str
    name_fits: bool


def render_certificate(
    image: Image.Image,
    full_name: str,
    motive_text: str,
    layout: ApplicationSettings,
) -> RenderResult:
    """Dibuja sobre una copia de trabajo. El texto no se recorta."""
    canvas = image if image.mode == "RGB" else image.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    warnings: list[str] = []
    name = full_name.upper() if layout.name_uppercase else full_name
    name_size, name_fits, used_two_lines = _draw_name(draw, canvas.size, name, layout)
    if used_two_lines:
        warnings.append("El nombre se escribió en dos líneas para que cupiera en el ancho disponible.")
    if not name_fits:
        warnings.append(
            "Advertencia: el nombre no cabe en el ancho disponible ni con el tamaño mínimo. "
            "No se recortó el texto."
        )
    motive_size, motive_warnings = _draw_motive(draw, canvas.size, motive_text, layout)
    warnings.extend(motive_warnings)
    _warn_if_near_edge(canvas.size, layout, warnings)
    return RenderResult(
        image=canvas,
        warnings=warnings,
        name_font_size=name_size,
        motive_font_size=motive_size,
        rendered_name=name,
        name_fits=name_fits,
    )


def _draw_name(draw: ImageDraw.ImageDraw, size: tuple[int, int], name: str, layout: ApplicationSettings):
    if not name.strip():
        return layout.name_font_size, True, False
    max_width = layout.name_max_width * size[0]
    lines = [name.strip()]
    font_size, fits = _fit_lines(lines, layout, max_width)
    used_two_lines = False
    if not fits and layout.name_two_lines:
        split_lines = _split_two_lines(name.strip())
        if len(split_lines) == 2:
            font_size, fits = _fit_lines(split_lines, layout, max_width)
            if fits or layout.name_overflow_policy != "block":
                lines = split_lines
                used_two_lines = True
    image_limit = _width_inside_image(size[0], layout.name_x * size[0], layout.name_align)
    font_size = _shrink_to_width(
        lines,
        font_name=layout.name_font,
        start=font_size,
        bold=layout.name_bold,
        italic=layout.name_italic,
        dpi=layout.dpi,
        max_width=image_limit,
    )
    fits = _lines_fit(lines, layout, font_size, max_width)
    color = _color(layout.name_color)
    line_gap = _points_to_px(font_size, layout.dpi) * 1.15
    top = layout.name_y * size[1]
    for index, line in enumerate(lines):
        font = load_font(
            layout.name_font,
            _points_to_px(font_size, layout.dpi),
            bold=layout.name_bold,
            italic=layout.name_italic,
        )
        _draw_aligned(
            draw,
            line,
            font,
            color,
            anchor_x=layout.name_x * size[0],
            top_y=top + index * line_gap,
            align=layout.name_align,
        )
    return font_size, fits, used_two_lines


def _fit_lines(lines: list[str], layout: ApplicationSettings, max_width: float):
    if not layout.name_autofit:
        size = _clamp_size(layout.name_font_size, layout)
        return size, _lines_fit(lines, layout, size, max_width)
    size = _clamp_size(layout.name_font_size, layout)
    while size > layout.name_min_font_size and not _lines_fit(lines, layout, size, max_width):
        size -= 1
    return size, _lines_fit(lines, layout, size, max_width)


def _lines_fit(lines: list[str], layout: ApplicationSettings, size: int, max_width: float) -> bool:
    font = load_font(
        layout.name_font,
        _points_to_px(size, layout.dpi),
        bold=layout.name_bold,
        italic=layout.name_italic,
    )
    return all(_ink_width(font, line) <= max_width for line in lines)


def _draw_motive(draw: ImageDraw.ImageDraw, size: tuple[int, int], motive_text: str, layout: ApplicationSettings):
    warnings: list[str] = []
    lines = motive_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any(line.strip() for line in lines):
        return layout.motive_font_size, warnings
    image_limit = _width_inside_image(size[0], layout.motive_x * size[0], layout.motive_align)
    font_size = _shrink_to_width(
        lines,
        font_name=layout.motive_font,
        start=layout.motive_font_size,
        bold=layout.motive_bold,
        italic=layout.motive_italic,
        dpi=layout.dpi,
        max_width=image_limit,
    )
    font_px = _points_to_px(font_size, layout.dpi)
    font = load_font(
        layout.motive_font,
        font_px,
        bold=layout.motive_bold,
        italic=layout.motive_italic,
    )
    color = _color(layout.motive_color)
    configured_width = layout.motive_max_width * size[0]
    top = layout.motive_y * size[1]
    gap = font_px * layout.motive_line_spacing
    for index, line in enumerate(lines):
        if line.strip() and _ink_width(font, line) > configured_width:
            warnings.append(f"Advertencia: la línea del motivo «{line[:80]}» supera el ancho máximo.")
        _draw_aligned(
            draw,
            line,
            font,
            color,
            anchor_x=layout.motive_x * size[0],
            top_y=top + index * gap,
            align=layout.motive_align,
        )
    if top + len(lines) * gap > size[1] * 0.98:
        warnings.append("Advertencia: el motivo se acerca al borde inferior de la plantilla.")
    return font_size, warnings


def _draw_aligned(draw, text, font, fill, *, anchor_x: float, top_y: float, align: str) -> None:
    if text == "":
        return
    bbox = font.getbbox(text)
    ink_width = bbox[2] - bbox[0]
    if align == "center":
        x = anchor_x - ink_width / 2 - bbox[0]
    elif align == "right":
        x = anchor_x - ink_width - bbox[0]
    else:
        x = anchor_x - bbox[0]
    draw.text((x, top_y - bbox[1]), text, font=font, fill=fill)


def _warn_if_near_edge(size: tuple[int, int], layout: ApplicationSettings, warnings: list[str]) -> None:
    margin = layout.safe_margin
    anchors = (layout.name_x, layout.name_y, layout.motive_x, layout.motive_y)
    if any(value < margin or value > 1 - margin for value in anchors):
        warnings.append("Advertencia: una posición queda muy cerca del borde de la página.")


def _split_two_lines(text: str) -> list[str]:
    words = text.split()
    if len(words) < 2:
        return [text]
    best: tuple[int, str, str] | None = None
    for index in range(1, len(words)):
        left = " ".join(words[:index])
        right = " ".join(words[index:])
        score = abs(len(left) - len(right))
        if best is None or score < best[0]:
            best = (score, left, right)
    if best is None:
        return [text]
    return [best[1], best[2]]


def _width_inside_image(image_width: float, anchor_x: float, align: str) -> float:
    """Ancho de tinta que cabe en el JPG según la posición y la alineación."""
    if align == "center":
        room = 2 * min(anchor_x, image_width - anchor_x)
    elif align == "right":
        room = anchor_x
    else:
        room = image_width - anchor_x
    return max(1.0, min(room, image_width))


def _shrink_to_width(
    lines: list[str],
    *,
    font_name: str,
    start: int,
    bold: bool,
    italic: bool,
    dpi: int,
    max_width: float,
) -> int:
    size = max(1, start)
    while size > 1 and not _width_fits(lines, font_name, size, bold, italic, dpi, max_width):
        size -= 1
    return size


def _width_fits(
    lines: list[str],
    font_name: str,
    size: int,
    bold: bool,
    italic: bool,
    dpi: int,
    max_width: float,
) -> bool:
    font = load_font(font_name, _points_to_px(size, dpi), bold=bold, italic=italic)
    return all(_ink_width(font, line) <= max_width for line in lines if line.strip())


def _ink_width(font, text: str) -> float:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return float(bbox[2] - bbox[0])


def _points_to_px(points: int, dpi: int) -> int:
    return max(1, round(points * dpi / 72))


def _clamp_size(size: int, layout: ApplicationSettings) -> int:
    return min(layout.name_max_font_size, max(size, layout.name_min_font_size))


def _color(value: str) -> tuple[int, int, int]:
    text = (value or "").strip().upper()
    if len(text) != 7 or not text.startswith("#") or any(char not in _HEX for char in text[1:]):
        return (26, 26, 26)
    return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
