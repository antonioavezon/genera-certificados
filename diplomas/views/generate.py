import io

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from diplomas.exceptions import DiplomaError, GenerationError
from diplomas.models import Participant
from diplomas.services.email.email_service import EmailService
from diplomas.services.file_service import open_directory
from diplomas.services.generation_service import GenerationService
from diplomas.services.logging_service import get_logger
from diplomas.services.participant_service import get_active_batch
from diplomas.services.preview_service import render_preview

logger = get_logger("app")


@require_http_methods(["GET", "POST"])
def generate_view(request):
    if request.method == "POST":
        return _run(request)
    service = GenerationService()
    report = service.preflight(send_email=False, regenerate=False)
    batch = get_active_batch()
    participants = []
    selected = None
    if batch is not None:
        participants = list(batch.participants.exclude(status="error"))
        requested = request.GET.get("p")
        if requested and requested.isdigit():
            selected = next((item for item in participants if item.pk == int(requested)), None)
        if selected is None and participants:
            selected = participants[0]
    preview_warnings: list[str] = []
    if selected is not None:
        try:
            preview_warnings = render_preview(selected).warnings
        except DiplomaError as exc:
            preview_warnings = [exc.user_message]
    return render(
        request,
        "diplomas/generate.html",
        {
            "report": report,
            "participants": participants,
            "selected": selected,
            "preview_warnings": preview_warnings,
        },
    )


def _run(request):
    return start_generation(request, send_email=request.POST.get("action") == "send")


def start_generation(request, *, send_email: bool, only_id: int | None = None):
    """Genera, o pregunta antes si ya hay diplomas. No reemplaza archivos."""
    answered = request.POST.get("again", "")
    back = "diplomas:list" if only_id else "diplomas:generate"
    service = GenerationService()
    try:
        report = service.preflight(send_email=send_email, regenerate=False, only_id=only_id)
    except DiplomaError as exc:
        messages.error(request, exc.user_message)
        return redirect(back)
    if not report.ok:
        messages.error(request, report.blockers[0])
        return redirect(back)
    if report.existing_count and answered not in {"yes", "no"}:
        question = (
            "¿Quiere volver a generar el certificado?"
            if report.existing_count == 1
            else "¿Quiere volver a generar los certificados?"
        )
        return render(
            request,
            "diplomas/confirm_again.html",
            {
                "question": question,
                "post_action": request.POST.get("action") or "generate",
                "only_id": only_id,
            },
        )
    try:
        batch = service.run(
            send_email=send_email,
            regenerate=False,
            numbered_copies=answered == "yes",
            only_id=only_id,
        )
    except GenerationError as exc:
        messages.error(request, exc.user_message)
        return redirect(back)
    except DiplomaError as exc:
        messages.error(request, exc.user_message)
        return redirect(back)
    messages.success(
        request,
        f"Lote #{batch.pk}: {batch.generated_count} generados, "
        f"{batch.already_exists_count} ya existían, {batch.skipped_count} omitidos, "
        f"{batch.error_count} con error.",
    )
    return redirect("diplomas:batch_detail", batch_id=batch.pk)


@require_http_methods(["GET"])
def preview_image(request):
    participant_id = request.GET.get("p", "")
    if not participant_id.isdigit():
        return HttpResponse("Seleccione un participante.", status=400, content_type="text/plain; charset=utf-8")
    participant = get_object_or_404(Participant, pk=int(participant_id))
    try:
        result = render_preview(participant)
    except DiplomaError as exc:
        logger.info("Vista previa rechazada: %s", exc.user_message)
        return HttpResponse(exc.user_message, status=400, content_type="text/plain; charset=utf-8")
    buffer = io.BytesIO()
    result.image.save(buffer, format="PNG")
    response = HttpResponse(buffer.getvalue(), content_type="image/png")
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def open_folder(request):
    from django.conf import settings

    from pathlib import Path

    try:
        open_directory(Path(settings.DIPLOMAS_OUTPUT_DIR))
        messages.info(request, "Se solicitó abrir la carpeta de diplomas.")
    except OSError:
        logger.exception("No se pudo abrir la carpeta de diplomas")
        messages.warning(
            request,
            f"No se pudo abrir el administrador de archivos. Los diplomas están en: {settings.DIPLOMAS_OUTPUT_DIR}",
        )
    return redirect(_safe_next(request.POST.get("next"), "diplomas:generate"))


@require_http_methods(["GET", "POST"])
def continue_pending(request):
    if request.method == "GET":
        return render(request, "diplomas/continue_pending.html")
    result = EmailService().continue_pending()
    _flash_email(request, result, "Continuación de envíos pendientes")
    return redirect(_safe_next(request.POST.get("next"), "diplomas:generate"))


@require_POST
def retry_failed(request):
    result = EmailService().retry_failed()
    _flash_email(request, result, "Reintento de correos fallidos")
    return redirect(_safe_next(request.POST.get("next"), "diplomas:generate"))


def _safe_next(candidate: str | None, fallback: str) -> str:
    if candidate and candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


def _flash_email(request, result, title: str) -> None:
    if result.stopped_reason:
        messages.error(request, result.stopped_reason)
        return
    level = messages.SUCCESS if result.failed == 0 and result.invalid == 0 else messages.WARNING
    messages.add_message(request, level, f"{title}. {result.summary}")
    for line in result.messages:
        messages.warning(request, line)
