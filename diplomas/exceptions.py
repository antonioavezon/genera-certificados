"""Excepciones de dominio.

El mensaje de cada excepción está pensado para mostrarse al usuario.
El detalle técnico se registra en los logs y no debe llegar a la interfaz.
"""


class DiplomaError(Exception):
    """Error controlado, con un texto comprensible para quien usa la aplicación."""

    def __init__(self, user_message: str, *, technical: str | None = None) -> None:
        self.user_message = user_message
        super().__init__(technical or user_message)


class InvalidListFileError(DiplomaError):
    """La lista no es un CSV o Excel utilizable."""


class CorruptFileError(DiplomaError):
    """El archivo existe, pero su contenido está dañado o incompleto."""


class InvalidTemplateError(DiplomaError):
    """La plantilla no se puede usar para un diploma."""


class InvalidMotiveError(DiplomaError):
    """El motivo no se puede leer o no es válido."""


class FontNotFoundError(DiplomaError):
    """La fuente configurada no está en la carpeta de fuentes."""


class DuplicateDiplomaError(DiplomaError):
    """Dos registros producirían el mismo archivo y la política lo impide."""


class GenerationError(DiplomaError):
    """No se pudo completar la generación de un diploma."""


class StoragePermissionError(DiplomaError):
    """No hay permiso para crear o escribir una carpeta necesaria."""


class EmailConfigurationError(DiplomaError):
    """El proveedor de correo no está disponible o está incompleto."""


class EmailSendError(DiplomaError):
    """El proveedor rechazó o no pudo completar un envío."""
