from django.shortcuts import render

from diplomas.services.logging_service import get_logger

logger = get_logger("app")


def csrf_failure(request, reason=""):
    logger.warning("Formulario rechazado por CSRF: %s", reason or "sin detalle")
    return render(
        request,
        "diplomas/error.html",
        {
            "title": "No se pudo confirmar el formulario",
            "message": "El formulario expiró o no es válido. Vuelva a la página e intente de nuevo.",
        },
        status=403,
    )
