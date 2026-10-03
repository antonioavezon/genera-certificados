"""Vista previa en memoria, sin escribir el PDF definitivo."""

from __future__ import annotations

from PIL import Image

from diplomas.exceptions import DiplomaError
from diplomas.models import Participant
from diplomas.services.config_service import get_settings
from diplomas.services.motive_service import get_motive
from diplomas.services.participant_service import get_active_batch
from diplomas.services.render_service import RenderResult, render_certificate
from diplomas.services.template_service import get_active_template, load_rgb


def render_preview(participant: Participant) -> RenderResult:
    batch = get_active_batch()
    if batch is None or participant.import_batch_id != batch.pk:
        raise DiplomaError("Seleccione un participante de la lista activa.")
    template = get_active_template()
    if template is None or not template.is_ready:
        raise DiplomaError("Cargue una plantilla válida antes de ver la vista previa.")
    motive = get_motive()
    if not motive.is_ready:
        raise DiplomaError("Escriba o cargue el motivo antes de ver la vista previa.")
    layout = get_settings()
    image = load_rgb(template, layout.dpi)
    result = render_certificate(image, participant.full_name, motive.text, layout)
    preview = result.image.copy()
    preview.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    result.image = preview
    return result
