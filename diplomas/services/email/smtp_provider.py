"""Envío SMTP opcional. La contraseña solo se lee del entorno."""

from __future__ import annotations

import smtplib
import uuid
from email.message import EmailMessage
from pathlib import Path

from django.conf import settings

from diplomas.exceptions import EmailConfigurationError, EmailSendError
from diplomas.services.email.base import EmailProvider, OutboundEmail, SendResult
from diplomas.services.logging_service import get_logger
from diplomas.services.validation_service import email_is_valid

logger = get_logger("email")


class SMTPProvider(EmailProvider):
    name = "smtp"

    def is_available(self) -> bool:
        return not self.validate_configuration()

    def unavailable_reason(self) -> str:
        problems = self.validate_configuration()
        if not problems:
            return ""
        return problems[0]

    def validate_configuration(self) -> list[str]:
        problems: list[str] = []
        if not settings.SMTP_HOST:
            problems.append("Falta el servidor SMTP. Complételo en el archivo .env.")
        if not settings.SMTP_PORT or settings.SMTP_PORT <= 0:
            problems.append("El puerto SMTP no es válido.")
        if not settings.SMTP_FROM or not email_is_valid(settings.SMTP_FROM):
            problems.append("Falta un remitente SMTP válido en el archivo .env.")
        if settings.SMTP_USER and not settings.SMTP_PASSWORD:
            problems.append("Falta la contraseña SMTP en el archivo .env.")
        if settings.SMTP_USE_TLS and settings.SMTP_USE_SSL:
            problems.append("Active solo una opción: TLS o SSL.")
        return problems

    def check_connection(self) -> None:
        """Abre el servidor y, si hay usuario, inicia sesión. No envía un mensaje."""
        problems = self.validate_configuration()
        if problems:
            raise EmailConfigurationError(problems[0])
        timeout = settings.EMAIL_TIMEOUT
        try:
            if settings.SMTP_USE_SSL:
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
            else:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
        except (OSError, smtplib.SMTPException, TimeoutError) as exc:
            logger.info("No se pudo conectar al servidor SMTP")
            raise EmailConfigurationError(
                "No hubo respuesta del servidor de correo. Revise el servidor, el puerto y TLS o SSL."
            ) from exc
        try:
            server.ehlo()
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                server.starttls()
                server.ehlo()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        except smtplib.SMTPException as exc:
            logger.info("El servidor SMTP rechazó la validación")
            raise EmailConfigurationError(
                "El servidor de correo rechazó el usuario o la contraseña."
            ) from exc
        except (OSError, TimeoutError) as exc:
            logger.info("Falló la validación SMTP")
            raise EmailConfigurationError(
                "No fue posible validar la conexión con el servidor de correo."
            ) from exc
        finally:
            try:
                server.quit()
            except (OSError, smtplib.SMTPException):
                logger.info("La conexión SMTP ya estaba cerrada.")

    def send(self, message: OutboundEmail) -> SendResult:
        problems = self.validate_configuration()
        if problems:
            raise EmailConfigurationError(problems[0])
        payload = _build_message(message)
        try:
            self._deliver(payload)
        except EmailSendError:
            raise
        except Exception as exc:
            logger.exception("Fallo SMTP inesperado")
            raise EmailSendError(
                "No fue posible enviar el correo. El envío quedó pendiente."
            ) from exc
        return SendResult(message_id=payload["Message-ID"] or "")

    def create_draft(self, message: OutboundEmail) -> SendResult:
        problems = self.validate_configuration()
        if problems:
            raise EmailConfigurationError(problems[0])
        drafts = Path(settings.DATA_DIR) / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        target = drafts / f"{uuid.uuid4().hex}.eml"
        target.write_bytes(_build_message(message).as_bytes())
        return SendResult(message_id=target.name)

    def _deliver(self, payload: EmailMessage) -> None:
        timeout = settings.EMAIL_TIMEOUT
        try:
            if settings.SMTP_USE_SSL:
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
            else:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
        except (OSError, smtplib.SMTPException, TimeoutError) as exc:
            logger.exception("No se pudo conectar al servidor SMTP")
            raise EmailSendError(
                "No hubo respuesta del servidor de correo. El envío quedó pendiente."
            ) from exc
        try:
            server.ehlo()
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                server.starttls()
                server.ehlo()
            if settings.SMTP_USER:
                try:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                except smtplib.SMTPException as exc:
                    logger.exception("El servidor SMTP rechazó las credenciales")
                    raise EmailSendError(
                        "El servidor de correo rechazó el usuario o la contraseña."
                    ) from exc
            server.send_message(payload)
        except EmailSendError:
            raise
        except (OSError, smtplib.SMTPException, TimeoutError) as exc:
            logger.exception("Fallo durante el envío SMTP")
            raise EmailSendError(
                "No fue posible enviar el correo. El envío quedó pendiente."
            ) from exc
        finally:
            try:
                server.quit()
            except (OSError, smtplib.SMTPException):
                logger.info("La conexión SMTP ya estaba cerrada.")


def _build_message(message: OutboundEmail) -> EmailMessage:
    payload = EmailMessage()
    payload["Subject"] = message.subject
    payload["From"] = settings.SMTP_FROM
    payload["To"] = message.to
    payload["Message-ID"] = f"<{uuid.uuid4().hex}@diplomas.local>"
    payload.set_content(message.body)
    if message.attachment_path is not None:
        data = message.attachment_path.read_bytes()
        payload.add_attachment(
            data,
            maintype="application",
            subtype="pdf",
            filename=message.attachment_name,
        )
    return payload
