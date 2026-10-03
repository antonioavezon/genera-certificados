#!/usr/bin/env python
"""Punto de entrada administrativo de Django."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. Active el entorno virtual e instale las dependencias."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
