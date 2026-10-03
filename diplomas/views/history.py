from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from diplomas.exceptions import DiplomaError
from diplomas.models import EmailDelivery, GenerationBatch, GenerationRecord
from diplomas.services.email.email_service import EmailService
from diplomas.services.file_service import contained_file
from diplomas.services.logging_service import get_logger
from diplomas.services.report_service import clear_history, filter_records, records_with_delivery, results_csv
from django.conf import settings

logger = get_logger("app")
_FILTERS = [
    ("todos", "Todos"),
    ("generados", "Generados"),
    ("errores", "Errores"),
    ("enviados", "Enviados"),
    ("fallidos", "Fallidos"),
    ("pendientes", "Pendientes"),
]


@require_http_methods(["GET"])
def history_list(request):
    batches = GenerationBatch.objects.select_related("import_batch").all()
    return render(request, "diplomas/history.html", {"batches": batches})


@require_POST
def clear_history_view(request):
    count = clear_history()
    if count:
        messages.success(
            request,
            "El historial se borró. Los diplomas de la carpeta se conservan.",
        )
    else:
        messages.info(request, "No había historial para borrar.")
    return redirect("diplomas:history")


@require_http_methods(["GET"])
def history_detail(request, batch_id: int):
    batch = get_object_or_404(GenerationBatch.objects.select_related("import_batch", "template"), pk=batch_id)
    selected = request.GET.get("estado", "todos")
    if selected not in dict(_FILTERS):
        selected = "todos"
    records = filter_records(records_with_delivery(batch), selected)
    page = Paginator(records, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "diplomas/batch_detail.html",
        {
            "batch": batch,
            "page_obj": page,
            "filters": _FILTERS,
            "selected": selected,
        },
    )


@require_http_methods(["GET"])
def export_csv(request, batch_id: int):
    batch = get_object_or_404(GenerationBatch, pk=batch_id)
    response = HttpResponse(results_csv(batch), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="resultados-lote-{batch.pk}.csv"'
    return response


@require_http_methods(["GET"])
def download_pdf(request, record_id: int):
    record = get_object_or_404(GenerationRecord, pk=record_id)
    try:
        path = contained_file(settings.DIPLOMAS_OUTPUT_DIR, record.filename)
    except DiplomaError as exc:
        messages.error(request, exc.user_message)
        return redirect("diplomas:batch_detail", batch_id=record.batch_id)
    if not path.is_file():
        messages.error(request, f"No se encontró el archivo {record.filename}.")
        return redirect("diplomas:batch_detail", batch_id=record.batch_id)
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)


@require_POST
def resend_email(request, delivery_id: int):
    delivery = get_object_or_404(EmailDelivery, pk=delivery_id)
    result = EmailService().resend(delivery)
    if result.stopped_reason:
        messages.error(request, result.stopped_reason)
    elif result.sent:
        messages.success(request, "El correo se reenvió.")
    else:
        messages.warning(request, result.summary)
    next_url = request.POST.get("next") or ""
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    if delivery.batch_id:
        return redirect("diplomas:batch_detail", batch_id=delivery.batch_id)
    return redirect("diplomas:history")
