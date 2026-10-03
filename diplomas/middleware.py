"""Evita que un error inesperado muestre un traceback en el navegador."""

from django.http import Http404
from django.shortcuts import render

from diplomas.exceptions import DiplomaError
from diplomas.services.logging_service import get_logger

logger = get_logger("app")


class FriendlyExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Http404:
            raise
        except DiplomaError as exc:
            logger.info("Solicitud rechazada: %s", exc.user_message)
            return render(
                request,
                "diplomas/error.html",
                {
                    "title": "No se pudo completar la acción",
                    "message": exc.user_message,
                },
                status=400,
            )
        except Exception:
            logger.exception("Error no controlado en la interfaz")
            return render(
                request,
                "diplomas/error.html",
                {
                    "title": "Ocurrió un problema",
                    "message": "Ocurrió un problema inesperado. El detalle quedó registrado para diagnóstico.",
                },
                status=500,
            )
