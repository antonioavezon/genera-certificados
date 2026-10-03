"""Pantalla para crear el .env de correo, validarlo y enviar una prueba."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings as django_settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from diplomas.exceptions import EmailConfigurationError, EmailSendError
from diplomas.forms import EMAIL_BODY_FIELDS, SmtpSettingsForm, layout_section
from diplomas.services.card_preview_service import (
    email_layout_thumbnail_png,
    gmail_provider_thumbnail_png,
    other_provider_thumbnail_png,
)
from diplomas.services.config_service import get_settings
from diplomas.services.email.base import OutboundEmail
from diplomas.services.email.env_service import apply_smtp_runtime, update_env_file
from diplomas.services.email.smtp_provider import SMTPProvider
from diplomas.services.logging_service import get_logger

logger = get_logger("email")


@require_GET
def email_settings_view(request):
    current = get_settings()
    host = (django_settings.SMTP_HOST or "").strip()
    return render(
        request,
        "diplomas/email_hub.html",
        {
            "password_set": bool(django_settings.SMTP_PASSWORD),
            "smtp_host": host,
            "subject": current.email_subject,
            "stamp": f"{host}-{int(bool(django_settings.SMTP_PASSWORD))}-{int(current.updated_at.timestamp())}",
        },
    )


@require_GET
def gmail_thumbnail(request):
    return _thumbnail(gmail_provider_thumbnail_png())


@require_GET
def other_thumbnail(request):
    return _thumbnail(other_provider_thumbnail_png())


@require_GET
def body_thumbnail(request):
    return _thumbnail(email_layout_thumbnail_png())


@require_http_methods(["GET", "POST"])
def gmail_view(request):
    return _provider(request, gmail=True, redirect_name="diplomas:configure_gmail")


@require_http_methods(["GET", "POST"])
def other_provider_view(request):
    return _provider(request, gmail=False, redirect_name="diplomas:configure_other")


@require_http_methods(["GET", "POST"])
def email_body_view(request):
    current = get_settings()
    data = request.POST if request.method == "POST" else None
    form = layout_section(data, current, EMAIL_BODY_FIELDS)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "El mensaje de correo se guardó.")
            return redirect("diplomas:configure_email_body")
        messages.error(request, "Hay datos del mensaje que no se pueden guardar. Revise los campos marcados.")
    return render(request, "diplomas/email_body.html", {"form": form})


def _provider(request, *, gmail: bool, redirect_name: str):
    if request.method == "POST":
        data = request.POST.copy()
        if gmail:
            data["host"] = "smtp.gmail.com"
            data["port"] = "587"
            data["use_tls"] = "on"
            data["use_ssl"] = ""
        form = SmtpSettingsForm(data, gmail=gmail)
        if form.is_valid():
            if (
                gmail
                and not form.cleaned_data.get("password")
                and not django_settings.SMTP_PASSWORD
            ):
                form.add_error("password", "Escriba la contraseña de aplicación de Gmail.")
                return _render_provider(request, form, gmail=gmail)
            _store(form.cleaned_data)
            action = request.POST.get("action")
            if action == "test":
                recipient = (
                    form.cleaned_data.get("test_to")
                    or form.cleaned_data.get("sender")
                    or form.cleaned_data.get("user")
                    or ""
                )
                _send_test(request, recipient)
            elif action == "validate":
                _validate(request)
            else:
                problems = SMTPProvider().validate_configuration()
                if problems:
                    for problem in problems:
                        messages.warning(request, problem)
                else:
                    messages.success(request, "El correo se guardó en .env.")
            return redirect(redirect_name)
        return _render_provider(request, form, gmail=gmail)
    initial = _initial()
    if gmail:
        initial.update({"host": "smtp.gmail.com", "port": 587, "use_tls": True, "use_ssl": False})
    return _render_provider(request, SmtpSettingsForm(initial=initial, gmail=gmail), gmail=gmail)


def _render_provider(request, form, *, gmail: bool):
    return render(
        request,
        "diplomas/email_gmail.html" if gmail else "diplomas/email_other.html",
        {"form": form, "password_set": bool(django_settings.SMTP_PASSWORD)},
    )


def _thumbnail(payload: bytes) -> HttpResponse:
    response = HttpResponse(payload, content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response


def _initial() -> dict:
    return {
        "host": django_settings.SMTP_HOST,
        "port": django_settings.SMTP_PORT or 587,
        "use_tls": django_settings.SMTP_USE_TLS,
        "use_ssl": django_settings.SMTP_USE_SSL,
        "user": django_settings.SMTP_USER,
        "sender": django_settings.SMTP_FROM,
        "test_to": django_settings.SMTP_USER or django_settings.SMTP_FROM,
    }


def _store(cleaned: dict) -> None:
    password = cleaned.get("password") or django_settings.SMTP_PASSWORD
    host = cleaned["host"].strip()
    port = int(cleaned["port"])
    use_tls = bool(cleaned.get("use_tls"))
    use_ssl = bool(cleaned.get("use_ssl"))
    user = (cleaned.get("user") or "").strip()
    sender = cleaned["sender"].strip()
    update_env_file(
        Path(django_settings.ENV_FILE),
        {
            "SMTP_HOST": host,
            "SMTP_PORT": str(port),
            "SMTP_USE_TLS": "true" if use_tls else "false",
            "SMTP_USE_SSL": "true" if use_ssl else "false",
            "SMTP_USER": user,
            "SMTP_PASSWORD": password,
            "SMTP_FROM": sender,
        },
    )
    apply_smtp_runtime(
        host=host,
        port=port,
        use_tls=use_tls,
        use_ssl=use_ssl,
        user=user,
        password=password,
        sender=sender,
    )
    current = get_settings()
    current.email_provider = "smtp"
    current.save(update_fields=["email_provider"])


def _validate(request) -> None:
    try:
        SMTPProvider().check_connection()
    except EmailConfigurationError as exc:
        logger.info("Validación de correo rechazada: %s", exc.user_message)
        messages.error(request, exc.user_message)
        return
    messages.success(request, "La conexión de correo es válida y quedó guardada en .env.")


def _send_test(request, recipient: str) -> None:
    recipient = recipient.strip()
    if not recipient:
        messages.error(request, "Escriba un correo de prueba.")
        return
    try:
        SMTPProvider().send(
            OutboundEmail(
                to=recipient,
                subject="Correo de prueba",
                body=(
                    "Este mensaje confirma que el envío de diplomas puede salir "
                    "con la configuración guardada."
                ),
                attachment_path=None,
                attachment_name="",
            )
        )
    except (EmailConfigurationError, EmailSendError) as exc:
        logger.info("Correo de prueba rechazado: %s", exc.user_message)
        messages.error(request, exc.user_message)
        return
    messages.success(request, f"Se envió el correo de prueba a {recipient}.")
