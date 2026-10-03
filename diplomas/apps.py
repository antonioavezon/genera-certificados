import logging

from django.apps import AppConfig

logger = logging.getLogger("diplomas")


class DiplomasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "diplomas"
    verbose_name = "Diplomas"

    def ready(self) -> None:
        from diplomas.services.file_service import cleanup_old_temp, ensure_directories

        try:
            problems = ensure_directories()
            for problem in problems:
                logger.error(problem)
            removed = cleanup_old_temp()
            if removed:
                logger.info("Se eliminaron %s archivos temporales antiguos.", removed)
        except Exception:
            logger.exception("No se pudieron preparar las carpetas de trabajo.")
