"""Filtros de logging compartidos por los tres archivos de registro."""


class LogContextFilter:
    """Garantiza los campos batch y participant en cada línea de log."""

    def filter(self, record):
        if not hasattr(record, "batch"):
            record.batch = "-"
        if not hasattr(record, "participant"):
            record.participant = "-"
        return True
