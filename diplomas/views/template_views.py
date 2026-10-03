from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from diplomas.exceptions import DiplomaError
from diplomas.forms import PageSelectForm, TemplateUploadForm
from diplomas.services.config_service import get_settings
from diplomas.services.template_service import (
    get_active_template,
    get_page_selection_template,
    import_upload,
    select_page,
    thumbnail_png,
)


@require_http_methods(["GET", "POST"])
def template_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "page":
                pending = get_page_selection_template()
                if pending is None:
                    messages.error(request, "No hay un PDF esperando la selección de página.")
                else:
                    form = PageSelectForm(request.POST, page_count=pending.page_count)
                    if not form.is_valid():
                        messages.error(request, "Seleccione un número de página válido.")
                    else:
                        select_page(pending, form.cleaned_data["page"], dpi=get_settings().dpi)
                        messages.success(request, "La página seleccionada quedó como plantilla activa.")
            else:
                form = TemplateUploadForm(request.POST, request.FILES)
                if not form.is_valid():
                    messages.error(request, "Seleccione una plantilla JPG, PNG o PDF.")
                else:
                    template = import_upload(form.cleaned_data["template_file"], dpi=get_settings().dpi)
                    if template.needs_page_selection:
                        messages.warning(
                            request,
                            f"El PDF contiene {template.page_count} páginas. "
                            "Seleccione la página que desea utilizar.",
                        )
                    else:
                        messages.success(request, "La plantilla se cargó correctamente.")
        except DiplomaError as exc:
            messages.error(request, exc.user_message)
        return redirect("diplomas:template")

    pending = get_page_selection_template()
    return render(
        request,
        "diplomas/template.html",
        {
            "upload_form": TemplateUploadForm(),
            "template_obj": get_active_template(),
            "pending": pending,
            "page_form": PageSelectForm(page_count=pending.page_count, initial={"page": 1}) if pending else None,
        },
    )


@require_GET
def template_thumbnail(request):
    template = get_active_template()
    if template is None or not template.is_ready:
        return HttpResponse(status=404)
    try:
        payload = thumbnail_png(template)
    except DiplomaError:
        return HttpResponse(status=404)
    response = HttpResponse(payload, content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response
