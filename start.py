#!/usr/bin/env python
"""Arranque local con Waitress.

Comprueba carpetas, aplica migraciones y abre el navegador en
http://127.0.0.1:8765. No usa el servidor de desarrollo de Django.
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_DEBUG", "false")

    import django

    django.setup()

    from django.conf import settings
    from django.core.management import call_command
    from waitress import serve

    from diplomas.exceptions import StoragePermissionError
    from diplomas.services.file_service import assert_writable, ensure_directories

    problems = ensure_directories()
    for problem in problems:
        print(problem)
    try:
        assert_writable(Path(settings.DIPLOMAS_OUTPUT_DIR), label="la carpeta de diplomas")
    except StoragePermissionError as exc:
        print(exc.user_message)
        sys.exit(1)
    if problems:
        sys.exit(1)

    call_command("migrate", interactive=False)
    call_command("collectstatic", interactive=False, verbosity=0)

    from config.wsgi import application

    port = int(os.environ.get("DIPLOMAS_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    print(f"Diplomas disponible en {url}")
    print("Para detenerlo, presione Ctrl+C.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(application, host="127.0.0.1", port=port, threads=8)


if __name__ == "__main__":
    main()
