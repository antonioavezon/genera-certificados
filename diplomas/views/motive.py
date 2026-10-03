from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from diplomas.exceptions import DiplomaError
from diplomas.forms import MotiveForm, MotiveUploadForm
from diplomas.services.card_preview_service import motive_thumbnail_png
from diplomas.services.motive_service import get_motive, import_txt, restore_previous, save_text


@require_http_methods(["GET", "POST"])
def motive_view(request):
    motive = get_motive()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "restore":
                restore_previous()
                messages.success(request, "Se restauró la versión anterior del motivo.")
            else:
                form = MotiveForm(request.POST)
                if form.is_valid():
                    save_text(form.cleaned_data["text"])
                    messages.success(request, "El motivo se guardó.")
        except DiplomaError as exc:
            messages.error(request, exc.user_message)
        return redirect("diplomas:motive")
    return render(
        request,
        "diplomas/motive.html",
        {
            "form": MotiveForm(initial={"text": motive.text}),
            "motive": motive,
        },
    )


@require_http_methods(["GET", "POST"])
def motive_upload_view(request):
    if request.method == "POST":
        form = MotiveUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Seleccione un archivo de texto.")
            return redirect("diplomas:motive_upload")
        try:
            import_txt(form.cleaned_data["motive_file"])
        except DiplomaError as exc:
            messages.error(request, exc.user_message)
            return redirect("diplomas:motive_upload")
        messages.success(request, "El motivo se cargó desde el archivo.")
        return redirect("diplomas:motive")
    return render(request, "diplomas/motive_upload.html", {"upload_form": MotiveUploadForm()})


@require_GET
def motive_thumbnail(request):
    motive = get_motive()
    if not motive.is_ready:
        return HttpResponse(status=404)
    response = HttpResponse(motive_thumbnail_png(motive), content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response
