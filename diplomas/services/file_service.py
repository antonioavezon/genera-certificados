"""Carpetas, hashes, cargas y movimiento seguro de archivos."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from diplomas.exceptions import DiplomaError, StoragePermissionError
from diplomas.services.logging_service import get_logger

logger = get_logger("app")


def project_directories() -> list[tuple[Path, str]]:
    return [
        (Path(settings.DIPLOMAS_OUTPUT_DIR), "la carpeta de diplomas"),
        (Path(settings.UPLOADS_DIR), "la carpeta de cargas"),
        (Path(settings.UPLOADS_DIR) / "lists", "la carpeta de listas"),
        (Path(settings.UPLOADS_DIR) / "templates", "la carpeta de plantillas"),
        (Path(settings.TEMP_DIR), "la carpeta temporal"),
        (Path(settings.LOGS_DIR), "la carpeta de registros"),
        (Path(settings.FONTS_DIR), "la carpeta de fuentes"),
        (Path(settings.DATA_DIR), "la carpeta de datos"),
    ]


def ensure_directories() -> list[str]:
    """Crea las carpetas de trabajo. Devuelve mensajes si alguna no se pudo crear."""
    problems: list[str] = []
    for path, label in project_directories():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("No se pudo crear %s", path)
            problems.append(
                f"No es posible escribir en {label}. Revise los permisos de la carpeta."
            )
    return problems


def assert_writable(path: Path, *, label: str) -> None:
    """Comprueba de verdad que se puede crear un archivo, no solo que la carpeta exista."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        logger.warning("Sin permiso de escritura en %s", path, exc_info=True)
        raise StoragePermissionError(
            f"No es posible escribir en {label}. Revise los permisos de la carpeta."
        ) from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def browser_filename(raw: str) -> str:
    """Usa solo el nombre, nunca una ruta enviada por el navegador."""
    name = Path(str(raw or "")).name.replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        return "archivo"
    return name[:255]


def contained_file(root: Path, name: str) -> Path:
    """Resuelve un nombre dentro de una carpeta y rechaza salirse de ella."""
    safe_name = Path(name).name
    if (
        not safe_name
        or safe_name in {".", ".."}
        or safe_name != name
        or "/" in name
        or "\\" in name
        or ".." in name
    ):
        raise DiplomaError("El nombre de archivo no es válido.")
    root_resolved = root.resolve()
    candidate = (root_resolved / safe_name).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise DiplomaError("La ruta solicitada no está permitida.")
    return candidate


def store_upload(uploaded: UploadedFile, directory: Path) -> tuple[Path, str]:
    """Guarda una carga con un nombre interno aleatorio. El original solo se conserva como etiqueta."""
    if uploaded.size is not None and uploaded.size > settings.MAX_UPLOAD_BYTES:
        raise DiplomaError("El archivo supera el tamaño máximo permitido.")
    original = browser_filename(uploaded.name)
    directory.mkdir(parents=True, exist_ok=True)
    # El sufijo definitivo lo asigna quien ya validó el contenido.
    temporary = directory / f".upload-{uuid.uuid4().hex}"
    written = 0
    try:
        with temporary.open("wb") as handle:
            for chunk in uploaded.chunks():
                written += len(chunk)
                if written > settings.MAX_UPLOAD_BYTES:
                    raise DiplomaError("El archivo supera el tamaño máximo permitido.")
                handle.write(chunk)
    except DiplomaError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        logger.exception("No se pudo guardar la carga")
        raise StoragePermissionError(
            "No es posible escribir en la carpeta de cargas. Revise los permisos de la carpeta."
        ) from exc
    return temporary, original


def remove_stored(directory: Path, stored_name: str) -> None:
    if not stored_name:
        return
    try:
        path = contained_file(directory, stored_name)
    except DiplomaError:
        logger.warning("Nombre interno rechazado al eliminar: %s", stored_name)
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("No se pudo eliminar %s", path.name, exc_info=True)


def move_into_place(source: Path, directory: Path, suffix: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = directory / stored_name
    os.replace(source, destination)
    return stored_name


def cleanup_old_temp(max_age_hours: int | None = None) -> int:
    hours = settings.TEMP_FILE_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    limit = datetime.now(timezone.utc) - timedelta(hours=hours)
    directory = Path(settings.TEMP_DIR)
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.iterdir():
        if not path.is_file() or path.name == ".gitkeep":
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < limit:
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("No se pudo eliminar el temporal %s", path.name, exc_info=True)
    return removed


def disk_space_problem(directory: Path, required_bytes: int) -> str | None:
    """Avisa solo cuando el espacio libre no alcanza una estimación razonable."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        usage = shutil_disk_usage(directory)
    except OSError:
        logger.warning("No se pudo consultar el espacio en %s", directory, exc_info=True)
        return None
    if usage < required_bytes:
        return (
            "No hay espacio suficiente en el disco para generar los diplomas. "
            "Libere espacio e intente de nuevo."
        )
    return None


def shutil_disk_usage(directory: Path) -> int:
    import shutil

    return shutil.disk_usage(directory).free


def open_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Windows" and hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if system == "Darwin" else ["xdg-open", str(path)]
    subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
