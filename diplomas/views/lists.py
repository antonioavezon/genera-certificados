from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from diplomas.exceptions import DiplomaError
from diplomas.forms import ParticipantForm, UploadListForm, build_mapping_form
from diplomas.models import Participant
from diplomas.services.card_preview_service import list_thumbnail_png
from diplomas.services.list_import_service import parse_list_file
from diplomas.services.logging_service import get_logger
from diplomas.services.participant_service import (
    activate_mapping,
    create_pending_from_upload,
    discard_pending,
    get_active_batch,
    get_pending_batch,
    revalidate_stored,
)
from diplomas.services.validation_service import validate_table
from diplomas.services.config_service import get_settings

logger = get_logger("app")


@require_http_methods(["GET", "POST"])
def list_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "revalidate":
            return _revalidate(request)
        if action == "save-participant":
            return _save_participant(request)
        if action == "delete-participant":
            return _delete_participant(request)
        if action == "certificate":
            return _certificate(request)
        return redirect("diplomas:list_upload")

    active = get_active_batch()
    context = {
        "active": active,
        "pending": get_pending_batch(),
        "page_obj": None,
        "participant_form": ParticipantForm(require_last_name=get_settings().require_last_name),
        "editing": None,
    }
    if active is not None:
        paginator = Paginator(active.participants.all(), 50)
        context["page_obj"] = paginator.get_page(request.GET.get("page"))
        edit_id = request.GET.get("editar", "")
        if edit_id.isdigit():
            editing = active.participants.filter(pk=int(edit_id)).first()
            if editing is not None:
                context["editing"] = editing
                context["participant_form"] = ParticipantForm(
                    initial={
                        "first_name": editing.first_name,
                        "last_name": editing.last_name,
                        "email": editing.email,
                    },
                    require_last_name=get_settings().require_last_name,
                )
    return render(request, "diplomas/list.html", context)


@require_http_methods(["GET", "POST"])
def list_upload_view(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "discard":
            discard_pending()
            messages.info(request, "Se descartó la carga pendiente.")
            return redirect("diplomas:list_upload")
        if action == "map":
            return _map_columns(request)
        return _upload(request)
    return render(request, "diplomas/list_upload.html", _upload_context(request))


def _upload_context(request):
    pending = get_pending_batch()
    context = {
        "upload_form": UploadListForm(),
        "pending": pending,
        "preview_headers": [],
        "preview_rows": [],
        "mapping_form": None,
    }
    if pending is None:
        return context
    try:
        table = parse_list_file(
            Path(settings.UPLOADS_DIR) / "lists" / pending.stored_name,
            pending.original_name,
            max_rows=settings.MAX_LIST_ROWS,
        )
    except DiplomaError as exc:
        messages.error(request, exc.user_message)
        discard_pending(pending)
        context["pending"] = None
        return context
    context["preview_headers"] = table.headers
    context["preview_rows"] = table.rows[:5]
    context["mapping_form"] = build_mapping_form(table.headers)
    context["pending_notes"] = table.warnings
    return context


def _upload(request):
    form = UploadListForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Seleccione un archivo CSV o Excel.")
        return redirect("diplomas:list_upload")
    try:
        batch = create_pending_from_upload(form.cleaned_data["data_file"])
    except DiplomaError as exc:
        logger.info("Lista rechazada: %s", exc.user_message)
        messages.error(request, exc.user_message)
        return redirect("diplomas:list_upload")
    messages.info(
        request,
        f"Se leyó «{batch.original_name}». Indique qué columna corresponde a cada dato.",
    )
    return redirect("diplomas:list_upload")


def _map_columns(request):
    pending = get_pending_batch()
    if pending is None:
        messages.error(request, "No hay una lista esperando que se asocien las columnas.")
        return redirect("diplomas:list_upload")
    form = build_mapping_form(pending.columns, data=request.POST)
    if not form.is_valid():
        messages.error(request, "Revise la asociación de columnas.")
        return redirect("diplomas:list_upload")
    path = Path(settings.UPLOADS_DIR) / "lists" / pending.stored_name
    try:
        table = parse_list_file(path, pending.original_name, max_rows=settings.MAX_LIST_ROWS)
        rows = validate_table(
            table.headers,
            table.rows,
            form.cleaned_data,
            require_last_name=get_settings().require_last_name,
        )
        activate_mapping(pending, form.cleaned_data, rows, " ".join(table.warnings))
    except DiplomaError as exc:
        messages.error(request, exc.user_message)
        return redirect("diplomas:list_upload")
    pending.refresh_from_db()
    messages.success(
        request,
        "Lista confirmada. "
        f"Total: {pending.total_rows}. Válidos: {pending.valid_count}. "
        f"Con advertencias: {pending.warning_count}. Con errores: {pending.error_count}. "
        "Los duplicados se conservan y quedan indicados.",
    )
    return redirect("diplomas:list")


def _revalidate(request):
    batch = get_active_batch()
    if batch is None:
        messages.error(request, "No hay una lista activa para volver a validar.")
        return redirect("diplomas:list")
    revalidate_stored(batch)
    messages.success(request, "La lista se volvió a validar con la configuración actual.")
    return redirect("diplomas:list")


def _save_participant(request):
    batch = get_active_batch()
    if batch is None:
        messages.error(request, "Confirme una lista antes de añadir participantes.")
        return redirect("diplomas:list")
    person_id = request.POST.get("participant", "")
    editing = None
    if person_id.isdigit():
        editing = get_object_or_404(Participant, pk=int(person_id), import_batch=batch)
    form = ParticipantForm(request.POST, require_last_name=get_settings().require_last_name)
    if not form.is_valid():
        messages.error(request, "Revise el nombre, el apellido y el correo.")
        return redirect("diplomas:list")
    data = form.cleaned_data
    if editing is None:
        Participant.objects.create(
            import_batch=batch,
            row_number=batch.participants.count() + 1,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
        )
        messages.success(request, "Se añadió el participante.")
    else:
        editing.first_name = data["first_name"]
        editing.last_name = data["last_name"]
        editing.email = data["email"]
        editing.save()
        messages.success(request, "Se actualizó el participante.")
    revalidate_stored(batch)
    return redirect("diplomas:list")


def _certificate(request):
    from diplomas.views.generate import start_generation

    batch = get_active_batch()
    if batch is None:
        messages.error(request, "No hay una lista activa.")
        return redirect("diplomas:list")
    person_id = request.POST.get("participant", "")
    if not person_id.isdigit():
        messages.error(request, "Seleccione el participante.")
        return redirect("diplomas:list")
    person = get_object_or_404(Participant, pk=int(person_id), import_batch=batch)
    return start_generation(request, send_email=False, only_id=person.pk)


def _delete_participant(request):
    batch = get_active_batch()
    if batch is None:
        messages.error(request, "No hay una lista activa.")
        return redirect("diplomas:list")
    person_id = request.POST.get("participant", "")
    if not person_id.isdigit():
        messages.error(request, "Seleccione el participante que desea borrar.")
        return redirect("diplomas:list")
    person = get_object_or_404(Participant, pk=int(person_id), import_batch=batch)
    name = person.full_name or f"fila {person.row_number}"
    person.delete()
    revalidate_stored(batch)
    messages.success(request, f"Se borró a {name} de la lista. El historial de diplomas se conserva.")
    return redirect("diplomas:list")


@require_GET
def list_thumbnail(request):
    batch = get_active_batch()
    if batch is None:
        return HttpResponse(status=404)
    response = HttpResponse(list_thumbnail_png(batch), content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response
