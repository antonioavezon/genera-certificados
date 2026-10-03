"""Outlook Desktop opcional y exclusivo de Windows.

pywin32 no se importa al cargar este módulo. En Linux el proveedor
simplemente queda no disponible.
"""

from __future__ import annotations

import platform

from diplomas.exceptions import EmailConfigurationError, EmailSendError
from diplomas.services.email.base import EmailProvider, OutboundEmail, SendResult
from diplomas.services.logging_service import get_logger

logger = get_logger("email")

_detection: tuple[bool, str] | None = None
_UNAVAILABLE = "Outlook Desktop compatible no fue detectado."


class OutlookProvider(EmailProvider):
    name = "outlook"

    def is_available(self) -> bool:
        return _detect()[0]

    def unavailable_reason(self) -> str:
        available, reason = _detect()
        return "" if available else reason

    def validate_configuration(self) -> list[str]:
        available, reason = _detect()
        return [] if available else [reason]

    def send(self, message: OutboundEmail) -> SendResult:
        return self._compose(message, send=True)

    def create_draft(self, message: OutboundEmail) -> SendResult:
        return self._compose(message, send=False)

    def _compose(self, message: OutboundEmail, *, send: bool) -> SendResult:
        available, reason = _detect()
        if not available:
            raise EmailConfigurationError(reason or _UNAVAILABLE)
        try:
            import win32com.client
        except ImportError as exc:
            raise EmailConfigurationError(_UNAVAILABLE) from exc
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)
            mail.To = message.to
            mail.Subject = message.subject
            mail.Body = message.body
            if message.attachment_path is not None:
                mail.Attachments.Add(str(message.attachment_path.resolve()))
            if send:
                mail.Send()
            else:
                mail.Save()
            message_id = str(getattr(mail, "EntryID", "") or "")
        except EmailConfigurationError:
            raise
        except Exception as exc:
            logger.exception("Fallo de automatización de Outlook")
            action = "enviar" if send else "guardar"
            raise EmailSendError(
                f"No fue posible {action} el correo con Outlook. El envío quedó pendiente."
            ) from exc
        return SendResult(message_id=message_id)


def _detect() -> tuple[bool, str]:
    global _detection
    if _detection is not None:
        return _detection
    if platform.system() != "Windows":
        _detection = (False, _UNAVAILABLE)
        return _detection
    try:
        import win32com.client
    except ImportError:
        logger.info("pywin32 no está instalado; Outlook queda desactivado.")
        _detection = (False, _UNAVAILABLE)
        return _detection
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        version = str(getattr(outlook, "Version", "") or "")
        if not version:
            _detection = (False, _UNAVAILABLE)
            return _detection
    except Exception:
        logger.info("Outlook Desktop no respondió a la automatización COM.", exc_info=True)
        _detection = (False, _UNAVAILABLE)
        return _detection
    _detection = (True, "")
    return _detection
