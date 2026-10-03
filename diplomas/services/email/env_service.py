"""Guarda la configuración SMTP en .env y la aplica al proceso en marcha."""

from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings

_KEYS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USE_TLS",
    "SMTP_USE_SSL",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
)


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Reemplaza claves SMTP y conserva el resto del archivo."""
    for value in updates.values():
        if "\n" in value or "\r" in value:
            raise ValueError("Un valor de correo no puede incluir saltos de línea.")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            rewritten.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            rewritten.append(f"{key}={_encode(updates[key])}")
            seen.add(key)
        else:
            rewritten.append(line)
    for key in _KEYS:
        if key in updates and key not in seen:
            rewritten.append(f"{key}={_encode(updates[key])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def apply_smtp_runtime(
    *,
    host: str,
    port: int,
    use_tls: bool,
    use_ssl: bool,
    user: str,
    password: str,
    sender: str,
) -> None:
    """Hace visibles los datos SMTP sin reiniciar el servidor."""
    os.environ["SMTP_HOST"] = host
    os.environ["SMTP_PORT"] = str(port)
    os.environ["SMTP_USE_TLS"] = "true" if use_tls else "false"
    os.environ["SMTP_USE_SSL"] = "true" if use_ssl else "false"
    os.environ["SMTP_USER"] = user
    os.environ["SMTP_PASSWORD"] = password
    os.environ["SMTP_FROM"] = sender
    settings.SMTP_HOST = host
    settings.SMTP_PORT = port
    settings.SMTP_USE_TLS = use_tls
    settings.SMTP_USE_SSL = use_ssl
    settings.SMTP_USER = user
    settings.SMTP_PASSWORD = password
    settings.SMTP_FROM = sender


def _encode(value: str) -> str:
    if any(char in value for char in " \t#\"'\\"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
