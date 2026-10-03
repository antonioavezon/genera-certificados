"""Configuración persistente de diseño, validación y huella de trazabilidad."""

from __future__ import annotations

import json
import re

from diplomas.models import ApplicationSettings
from diplomas.services.file_service import sha256_text
from diplomas.services.font_service import font_exists

_HEX = re.compile(r"#[0-9A-F]{6}")
_ALIGNMENTS = {"left", "center", "right"}
_SNAPSHOT_FIELDS = (
    "name_x",
    "name_y",
    "name_font",
    "name_font_size",
    "name_min_font_size",
    "name_max_font_size",
    "name_color",
    "name_bold",
    "name_italic",
    "name_align",
    "name_max_width",
    "name_uppercase",
    "name_autofit",
    "name_two_lines",
    "name_overflow_policy",
    "motive_x",
    "motive_y",
    "motive_font",
    "motive_font_size",
    "motive_color",
    "motive_bold",
    "motive_italic",
    "motive_align",
    "motive_line_spacing",
    "motive_max_width",
    "dpi",
    "safe_margin",
    "collision_policy",
    "require_last_name",
    "email_subject",
    "email_body",
    "email_provider",
)


def get_settings() -> ApplicationSettings:
    settings_obj, _created = ApplicationSettings.objects.get_or_create(pk=1)
    return settings_obj


def configuration_problems(settings_obj: ApplicationSettings | None = None) -> list[str]:
    current = settings_obj or get_settings()
    problems: list[str] = []
    if not _HEX.fullmatch((current.name_color or "").upper()):
        problems.append("El color del nombre no es un hexadecimal válido, por ejemplo #F26522.")
    if not _HEX.fullmatch((current.motive_color or "").upper()):
        problems.append("El color del motivo no es un hexadecimal válido, por ejemplo #F26522.")
    if current.name_align not in _ALIGNMENTS or current.motive_align not in _ALIGNMENTS:
        problems.append("La alineación debe ser izquierda, centro o derecha.")
    if not font_exists(current.name_font):
        problems.append("La fuente seleccionada no está disponible.")
    if not font_exists(current.motive_font):
        problems.append("La fuente del motivo no está disponible.")
    if current.name_min_font_size > current.name_font_size:
        problems.append("El tamaño mínimo del nombre no puede ser mayor que el tamaño elegido.")
    if current.name_font_size > current.name_max_font_size:
        problems.append("El tamaño del nombre no puede ser mayor que el tamaño máximo.")
    if not 0 <= current.name_x <= 1 or not 0 <= current.name_y <= 1:
        problems.append("La posición del nombre debe estar entre 0 % y 100 %.")
    if not 0 <= current.motive_x <= 1 or not 0 <= current.motive_y <= 1:
        problems.append("La posición del motivo debe estar entre 0 % y 100 %.")
    if not 0.05 <= current.name_max_width <= 1 or not 0.05 <= current.motive_max_width <= 1:
        problems.append("El ancho máximo debe estar entre 5 % y 100 %.")
    if not 72 <= current.dpi <= 600:
        problems.append("La resolución debe estar entre 72 y 600 DPI.")
    if not 0.8 <= current.motive_line_spacing <= 3:
        problems.append("El interlineado debe estar entre 0,8 y 3.")
    if not current.email_subject.strip():
        problems.append("Escriba un asunto para el correo.")
    if "{nombre}" not in current.email_body and not current.email_body.strip():
        problems.append("Escriba el cuerpo del correo.")
    return problems


def snapshot(settings_obj: ApplicationSettings | None = None) -> dict:
    current = settings_obj or get_settings()
    data = {}
    for field in _SNAPSHOT_FIELDS:
        value = getattr(current, field)
        if isinstance(value, float):
            value = round(value, 6)
        data[field] = value
    return data


def snapshot_hash(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return sha256_text(raw)


def reset_defaults() -> ApplicationSettings:
    current = get_settings()
    for field in current._meta.fields:
        if field.primary_key or field.name == "updated_at":
            continue
        setattr(current, field.name, field.get_default())
    current.save()
    return current
