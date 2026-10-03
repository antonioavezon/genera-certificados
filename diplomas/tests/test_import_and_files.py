import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from diplomas.exceptions import CorruptFileError, DiplomaError, InvalidListFileError, StoragePermissionError
from diplomas.services.file_service import assert_writable, browser_filename, contained_file, ensure_directories
from diplomas.services.list_import_service import parse_list_file
from diplomas.services.logging_service import get_logger
from diplomas.tests.helpers import FIXTURES


class ListImportTests(SimpleTestCase):
    def test_csv_utf8_bom(self):
        table = parse_list_file(FIXTURES / "lista_valida.csv", "lista_valida.csv", max_rows=100)
        self.assertEqual(table.headers[0], "Nombre")
        self.assertEqual(table.rows[0][0], "Ana")
        self.assertEqual(len(table.rows), 3)

    def test_xlsx(self):
        table = parse_list_file(FIXTURES / "lista_valida.xlsx", "lista_valida.xlsx", max_rows=100)
        self.assertEqual(table.rows[1][2], "luis.mendoza@example.com")
        self.assertTrue(any("primera hoja" in warning for warning in table.warnings))

    def test_corrupt_csv(self):
        with self.assertRaises((InvalidListFileError, CorruptFileError)):
            parse_list_file(FIXTURES / "corrupto.csv", "corrupto.csv", max_rows=100)

    def test_corrupt_xlsx(self):
        with self.assertRaises((InvalidListFileError, CorruptFileError)) as caught:
            parse_list_file(FIXTURES / "corrupto.xlsx", "lista.xlsx", max_rows=100)
        self.assertIn("Excel", caught.exception.user_message)

    def test_semicolon_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lista.csv"
            path.write_text(
                "Nombre;Apellido;Correo\nAna;Torres;ana.torres@example.com\n",
                encoding="utf-8",
            )
            table = parse_list_file(path, "lista.csv", max_rows=20)
        self.assertEqual(table.rows[0], ["Ana", "Torres", "ana.torres@example.com"])


class FolderTests(SimpleTestCase):
    def test_missing_output_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "generated"
            self.assertFalse(target.exists())
            with override_settings(DIPLOMAS_OUTPUT_DIR=target):
                ensure_directories()
            self.assertTrue(target.is_dir())

    def test_unwritable_directory_has_clear_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solo-lectura"
            path.mkdir()
            path.chmod(0o555)
            try:
                with self.assertRaises(StoragePermissionError) as caught:
                    assert_writable(path, label="la carpeta de diplomas")
                self.assertIn("escribir", caught.exception.user_message)
                self.assertIn("permisos", caught.exception.user_message)
            finally:
                path.chmod(0o755)

    def test_browser_filename_drops_traversal(self):
        self.assertEqual(browser_filename("../../secreto.pdf"), "secreto.pdf")
        with self.assertRaises(DiplomaError):
            contained_file(Path(tempfile.gettempdir()), "../secreto.pdf")


class LogTests(SimpleTestCase):
    def test_generation_log_receives_message(self):
        from django.conf import settings

        get_logger("generation").info("marca-de-prueba-diplomas")
        text = Path(settings.LOGS_DIR, "generation.log").read_text(encoding="utf-8")
        self.assertIn("marca-de-prueba-diplomas", text)


class OutlookAvailabilityTests(unittest.TestCase):
    def test_linux_does_not_import_pywin32(self):
        import ast
        import inspect
        import platform
        import sys

        import diplomas.services.email.outlook_provider as outlook

        tree = ast.parse(inspect.getsource(outlook))
        for node in tree.body:
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            self.assertFalse(any(name.startswith("win32com") for name in modules))
        self.assertNotIn("win32com", sys.modules)
        self.assertNotIn("win32com.client", sys.modules)
        if platform.system() != "Windows":
            from diplomas.exceptions import EmailConfigurationError
            from diplomas.services.email.base import OutboundEmail

            provider = outlook.OutlookProvider()
            self.assertFalse(provider.is_available())
            self.assertIn("Outlook Desktop compatible no fue detectado.", provider.unavailable_reason())
            with self.assertRaises(EmailConfigurationError):
                provider.send(
                    OutboundEmail("ana@example.com", "Asunto", "Cuerpo", None, "ana.pdf")
                )
            self.assertNotIn("win32com", sys.modules)
            self.assertNotIn("win32com.client", sys.modules)
