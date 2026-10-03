"""Acceso a los loggers de aplicación, generación y correo."""

from __future__ import annotations

import logging

_LOGGERS = {
    "app": "diplomas",
    "generation": "diplomas.generation",
    "email": "diplomas.email",
}


def get_logger(channel: str = "app") -> logging.Logger:
    return logging.getLogger(_LOGGERS.get(channel, _LOGGERS["app"]))
