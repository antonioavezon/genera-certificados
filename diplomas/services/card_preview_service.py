"""Miniaturas de la lista y del motivo, del mismo tamaño que la de la plantilla."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from diplomas.exceptions import FontNotFoundError
from diplomas.models import ImportBatch, Motive
from diplomas.services.config_service import get_settings
from diplomas.services.font_service import load_font
from diplomas.services.template_service import fit_thumbnail_size, get_active_template

_INK = (20, 48, 68)
_BRAND = (11, 58, 91)
_LINE = (213, 222, 230)
_ROW = (247, 249, 251)
_HEADER = (255, 255, 255)


def preview_size() -> tuple[int, int]:
    template = get_active_template()
    if template is not None and template.width_px > 0 and template.height_px > 0:
        return fit_thumbnail_size(template.width_px, template.height_px)
    return fit_thumbnail_size(935, 720)


def list_thumbnail_png(batch: ImportBatch) -> bytes:
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    people = list(batch.participants.order_by("row_number", "id"))
    margin = max(10, width // 30)
    inner_w = width - margin * 2
    header_h = max(28, height // 7)
    min_row = max(24, height // 11)
    body_h = height - margin * 2 - header_h
    capacity = max(1, body_h // min_row)
    hidden = max(0, len(people) - capacity)
    shown = people[: capacity if hidden == 0 else max(1, capacity - 1)]
    row_h = body_h / max(len(shown) + (1 if hidden else 0), 1)
    font = _font(max(12, int(min(row_h, header_h) * 0.42)))
    header_font = _font(max(12, int(header_h * 0.38)), bold=True)
    columns = (
        (0.08, "#"),
        (0.28, "Nombre"),
        (0.28, "Apellido"),
        (0.36, "Correo"),
    )
    top = margin
    draw.rectangle((margin, top, width - margin, top + header_h), fill=_BRAND)
    _table_row(
        draw,
        [label for _, label in columns],
        [share for share, _ in columns],
        font=header_font,
        fill=_HEADER,
        left=margin,
        top=top,
        width=inner_w,
        height=header_h,
    )
    top += header_h
    for index, person in enumerate(shown):
        if index % 2 == 1:
            draw.rectangle((margin, top, width - margin, top + row_h), fill=_ROW)
        _table_row(
            draw,
            [str(person.row_number), person.first_name, person.last_name, person.email],
            [share for share, _ in columns],
            font=font,
            fill=_INK,
            left=margin,
            top=top,
            width=inner_w,
            height=row_h,
        )
        draw.line((margin, top, width - margin, top), fill=_LINE)
        top += row_h
    if hidden:
        draw.rectangle((margin, top, width - margin, top + row_h), fill=_ROW)
        note = _font(max(12, int(row_h * 0.38)))
        label = f"y {hidden} más"
        draw.text((width / 2, top + row_h / 2), label, font=note, fill=_INK, anchor="mm")
    draw.rectangle((margin, margin, width - margin, height - margin), outline=_LINE)
    return _png(image)


def name_layout_thumbnail_png() -> bytes:
    """Muestra el nombre con la fuente, el color y la posición configurados."""
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    layout = get_settings()
    text = "NOMBRE APELLIDO" if layout.name_uppercase else "Nombre Apellido"
    font = _fit_line(
        text,
        width * 0.82,
        font_name=layout.name_font,
        bold=layout.name_bold,
        italic=layout.name_italic,
        size=max(18, height // 7),
    )
    draw = ImageDraw.Draw(image)
    _draw_anchored(
        draw,
        text,
        font,
        _hex_color(layout.name_color),
        width,
        height,
        layout.name_x,
        layout.name_y,
        layout.name_align,
    )
    return _png(image)


def motive_layout_thumbnail_png(motive: Motive) -> bytes:
    """Muestra el motivo escrito, o una muestra con su estilo si todavía no hay texto."""
    if motive.is_ready:
        return motive_thumbnail_png(motive)
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    layout = get_settings()
    lines = ["Motivo del diploma", "en el certificado"]
    font, gap = _fit_block(
        lines,
        width * max(layout.motive_max_width, 0.2),
        height * 0.7,
        font_name=layout.motive_font,
        bold=layout.motive_bold,
        italic=layout.motive_italic,
        spacing=layout.motive_line_spacing,
    )
    draw = ImageDraw.Draw(image)
    color = _hex_color(layout.motive_color)
    block_h = gap * (len(lines) - 1) + _line_height(font)
    top = height * layout.motive_y - block_h / 2
    top = min(max(top, 8), height - block_h - 8)
    for index, line in enumerate(lines):
        _draw_anchored(draw, line, font, color, width, height, layout.motive_x, 0, layout.motive_align, y_px=top + index * gap)
    return _png(image)


def output_layout_thumbnail_png() -> bytes:
    """Muestra el archivo y la resolución con los que sale el diploma."""
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = max(14, width // 16)
    draw.rectangle((margin, margin, width - margin, height - margin), outline=_BRAND, width=max(2, width // 140))
    layout = get_settings()
    title_font = _font(max(16, width // 18), bold=True)
    body_font = _font(max(13, width // 24))
    policy = "Bloquea el duplicado" if layout.collision_policy == "block" else "Añade _2, _3…"
    lines = ["nombre.apellido.pdf", f"{layout.dpi} DPI", policy]
    gap = _line_height(title_font) * 1.45
    top = height / 2 - gap
    draw.text((width / 2, top), lines[0], font=title_font, fill=_BRAND, anchor="mm")
    draw.text((width / 2, top + gap), lines[1], font=body_font, fill=_INK, anchor="mm")
    draw.text((width / 2, top + gap * 2), lines[2], font=body_font, fill=_INK, anchor="mm")
    return _png(image)


def gmail_provider_thumbnail_png() -> bytes:
    """Muestra Gmail y si la contraseña de aplicación ya está guardada."""
    from django.conf import settings

    ready = (settings.SMTP_HOST or "").strip().lower() == "smtp.gmail.com" and bool(settings.SMTP_PASSWORD)
    return _mail_card("Gmail", "smtp.gmail.com", "Contraseña lista" if ready else "Falta la contraseña")


def other_provider_thumbnail_png() -> bytes:
    """Muestra el servidor SMTP cuando no es Gmail."""
    from django.conf import settings

    host = (settings.SMTP_HOST or "").strip()
    if not host or host.lower() == "smtp.gmail.com":
        return _mail_card("SMTP", "Otro servidor", "Puerto y remitente")
    cipher = "TLS" if settings.SMTP_USE_TLS else "SSL" if settings.SMTP_USE_SSL else "Sin cifrado"
    return _mail_card(host, f"Puerto {settings.SMTP_PORT or 587}", cipher)


def email_layout_thumbnail_png() -> bytes:
    """Muestra el asunto y la primera línea del mensaje."""
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = max(14, width // 16)
    header_h = max(36, height // 6)
    draw.rectangle((margin, margin, width - margin, margin + header_h), fill=_BRAND)
    layout = get_settings()
    subject = (layout.email_subject or "Asunto").replace("{nombre}", "Nombre Apellido")
    body = _first_line(layout.email_body).replace("{nombre}", "Nombre Apellido")
    header_font = _font(max(14, int(header_h * 0.38)), bold=True)
    body_font = _font(max(13, width // 26))
    draw.text(
        (margin + 12, margin + header_h / 2),
        _ellipsis(draw, subject, header_font, width - margin * 2 - 24),
        font=header_font,
        fill=_HEADER,
        anchor="lm",
    )
    draw.text(
        (margin + 12, margin + header_h + max(22, height // 8)),
        _ellipsis(draw, body, body_font, width - margin * 2 - 24),
        font=body_font,
        fill=_INK,
        anchor="lm",
    )
    providers = {"none": "Sin correo", "smtp": "SMTP", "outlook": "Outlook"}
    draw.text(
        (margin + 12, height - margin - 8),
        providers.get(layout.email_provider, layout.email_provider),
        font=body_font,
        fill=_BRAND,
        anchor="ls",
    )
    draw.rectangle((margin, margin, width - margin, height - margin), outline=_LINE)
    return _png(image)


def _mail_card(title: str, line: str, status: str) -> bytes:
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = max(14, width // 16)
    header_h = max(36, height // 6)
    draw.rectangle((margin, margin, width - margin, margin + header_h), fill=_BRAND)
    title_font = _font(max(16, int(header_h * 0.42)), bold=True)
    body_font = _font(max(13, width // 26))
    draw.text(
        (margin + 12, margin + header_h / 2),
        _ellipsis(draw, title, title_font, width - margin * 2 - 24),
        font=title_font,
        fill=_HEADER,
        anchor="lm",
    )
    draw.text(
        (margin + 12, margin + header_h + max(28, height // 6)),
        _ellipsis(draw, line, body_font, width - margin * 2 - 24),
        font=body_font,
        fill=_INK,
        anchor="lm",
    )
    draw.text(
        (margin + 12, height - margin - 8),
        _ellipsis(draw, status, body_font, width - margin * 2 - 24),
        font=body_font,
        fill=_BRAND,
        anchor="ls",
    )
    draw.rectangle((margin, margin, width - margin, height - margin), outline=_LINE)
    return _png(image)


def motive_thumbnail_png(motive: Motive) -> bytes:
    width, height = preview_size()
    image = Image.new("RGB", (width, height), "white")
    lines = _motive_lines(motive.text)
    if not lines:
        return _png(image)
    layout = get_settings()
    max_width = width * 0.86
    max_height = height * 0.78
    font, gap = _fit_block(
        lines,
        max_width,
        max_height,
        font_name=layout.motive_font,
        bold=layout.motive_bold,
        italic=layout.motive_italic,
        spacing=layout.motive_line_spacing,
    )
    block_h = gap * max(len(lines) - 1, 0) + _line_height(font)
    top = (height - block_h) / 2
    draw = ImageDraw.Draw(image)
    color = _hex_color(layout.motive_color)
    for index, line in enumerate(lines):
        if not line:
            continue
        bbox = font.getbbox(line)
        ink_width = bbox[2] - bbox[0]
        x = (width - ink_width) / 2 - bbox[0]
        y = top + index * gap - bbox[1]
        draw.text((x, y), line, font=font, fill=color)
    return _png(image)


def _fit_line(text: str, max_width: float, *, font_name: str, bold: bool, italic: bool, size: int):
    size = max(8, min(size, 72))
    font = _named_font(font_name, size, bold=bold, italic=italic)
    while size > 8 and _ink(font, text) > max_width:
        size -= 1
        font = _named_font(font_name, size, bold=bold, italic=italic)
    return font


def _draw_anchored(draw, text, font, color, width, height, x_frac, y_frac, align, y_px=None) -> None:
    bbox = font.getbbox(text)
    ink_w = max(1, bbox[2] - bbox[0])
    ink_h = max(1, bbox[3] - bbox[1])
    anchor_x = width * float(x_frac)
    if align == "right":
        x = anchor_x - ink_w
    elif align == "center":
        x = anchor_x - ink_w / 2
    else:
        x = anchor_x
    y = y_px if y_px is not None else height * float(y_frac) - ink_h / 2
    x = min(max(x, 6), max(6, width - ink_w - 6))
    y = min(max(y, 6), max(6, height - ink_h - 6))
    draw.text((x - bbox[0], y - bbox[1]), text, font=font, fill=color)


def _first_line(text: str) -> str:
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if line.strip():
            return line.strip()
    return "Mensaje del diploma"


def _motive_lines(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _fit_block(
    lines: list[str],
    max_width: float,
    max_height: float,
    *,
    font_name: str,
    bold: bool,
    italic: bool,
    spacing: float,
) -> tuple[ImageFont.ImageFont, float]:
    for size in range(64, 9, -1):
        font = _named_font(font_name, size, bold=bold, italic=italic)
        gap = _line_height(font) * max(spacing, 1)
        widest = max((_ink(font, line) for line in lines), default=0)
        block_h = gap * max(len(lines) - 1, 0) + _line_height(font)
        if widest <= max_width and block_h <= max_height:
            return font, gap
    font = _named_font(font_name, 10, bold=bold, italic=italic)
    return font, _line_height(font) * max(spacing, 1)


def _table_row(draw, values, shares, *, font, fill, left, top, width, height) -> None:
    x = left
    for value, share in zip(values, shares, strict=True):
        column_w = width * share
        text = _ellipsis(draw, str(value or ""), font, column_w - 12)
        draw.text((x + 6, top + height / 2), text, font=font, fill=fill, anchor="lm")
        x += column_w


def _ellipsis(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed + "…", font=font) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}…" if trimmed else "…"


def _named_font(name: str, size: int, *, bold: bool, italic: bool):
    try:
        return load_font(name, size, bold=bold, italic=italic)
    except FontNotFoundError:
        return _font(size, bold=bold)


def _font(size: int, *, bold: bool = False):
    try:
        return load_font("DejaVuSans.ttf", size, bold=bold)
    except FontNotFoundError:
        return ImageFont.load_default()


def _ink(font, text: str) -> float:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _line_height(font) -> float:
    bbox = font.getbbox("Ag")
    return max(1, bbox[3] - bbox[1])


def _hex_color(value: str) -> tuple[int, int, int]:
    cleaned = (value or "").strip()
    if len(cleaned) == 7 and cleaned.startswith("#"):
        try:
            return (int(cleaned[1:3], 16), int(cleaned[3:5], 16), int(cleaned[5:7], 16))
        except ValueError:
            pass
    return (51, 51, 51)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
