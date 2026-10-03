from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from diplomas.forms import MOTIVE_LAYOUT_FIELDS, NAME_LAYOUT_FIELDS, OUTPUT_LAYOUT_FIELDS, layout_section
from diplomas.services.card_preview_service import (
    email_layout_thumbnail_png,
    motive_layout_thumbnail_png,
    name_layout_thumbnail_png,
    output_layout_thumbnail_png,
)
from diplomas.services.config_service import get_settings
from diplomas.services.motive_service import get_motive

_SECTIONS = {
    "nombre": ("Vista de nombre", "diplomas:configure_name", NAME_LAYOUT_FIELDS),
    "motivo": ("Vista de motivo", "diplomas:configure_motive", MOTIVE_LAYOUT_FIELDS),
    "salida": ("Salida de certificado", "diplomas:configure_output", OUTPUT_LAYOUT_FIELDS),
}


@require_http_methods(["GET"])
def configure_view(request):
    current = get_settings()
    motive = get_motive()
    return render(
        request,
        "diplomas/configure.html",
        {"stamp": f"{int(current.updated_at.timestamp())}-{motive.content_hash}"},
    )


@require_GET
def configure_name_thumbnail(request):
    return _thumbnail(name_layout_thumbnail_png())


@require_GET
def configure_motive_thumbnail(request):
    return _thumbnail(motive_layout_thumbnail_png(get_motive()))


@require_GET
def configure_output_thumbnail(request):
    return _thumbnail(output_layout_thumbnail_png())


@require_GET
def configure_email_thumbnail(request):
    return _thumbnail(email_layout_thumbnail_png())


def _thumbnail(payload: bytes) -> HttpResponse:
    response = HttpResponse(payload, content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response


@require_http_methods(["GET", "POST"])
def configure_name(request):
    return _section(request, "nombre")


@require_http_methods(["GET", "POST"])
def configure_motive_layout(request):
    return _section(request, "motivo")


@require_http_methods(["GET", "POST"])
def configure_output(request):
    return _section(request, "salida")


def _section(request, key: str):
    title, redirect_name, fields = _SECTIONS[key]
    current = get_settings()
    data = request.POST if request.method == "POST" else None
    form = layout_section(data, current, fields)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "La configuración se guardó.")
            return redirect(redirect_name)
        messages.error(request, "Hay datos de configuración que no se pueden guardar. Revise los campos marcados.")
    return render(
        request,
        "diplomas/configure_section.html",
        {"form": form, "title": title},
    )
