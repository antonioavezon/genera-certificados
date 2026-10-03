from django.conf import settings

from diplomas.services.email.email_service import EmailService
from diplomas.services.logging_service import get_logger

logger = get_logger("app")


def shell(request):
    try:
        ready, issues = EmailService().provider_ready()
    except Exception:
        logger.exception("No se pudo evaluar el estado del correo.")
        ready, issues = False, []
    return {
        "email_ready": ready,
        "email_issues": issues,
        "output_dir": settings.DIPLOMAS_OUTPUT_DIR,
    }
