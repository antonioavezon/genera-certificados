"""Lectura de listas CSV UTF-8 y XLSX, sin confiar solo en la extensión."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from diplomas.exceptions import CorruptFileError, InvalidListFileError
from diplomas.services.logging_service import get_logger

logger = get_logger("app")


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)


def parse_list_file(path: Path, original_name: str, *, max_rows: int) -> ParsedTable:
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.exception("No se pudo leer la lista")
        raise InvalidListFileError("No se pudo leer el archivo de la lista.") from exc
    if not data.strip():
        raise InvalidListFileError("El archivo está vacío.")
    kind = _detect_kind(data, original_name)
    if kind == "xlsx":
        table = _parse_xlsx(path)
    else:
        table = _parse_csv(data)
    if not table.headers:
        raise InvalidListFileError("No se encontraron columnas en la lista.")
    if not table.rows:
        raise InvalidListFileError("La lista no contiene participantes.")
    if len(table.rows) > max_rows:
        raise InvalidListFileError(f"La lista supera el máximo de {max_rows} filas.")
    return table


def _detect_kind(data: bytes, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or data[:5] == b"%PDF-":
        raise InvalidListFileError("El archivo no es una lista CSV o Excel.")
    if data[:2] == b"PK":
        return "xlsx"
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        raise InvalidListFileError(
            "El archivo seleccionado no es un documento Excel válido o está dañado."
        )
    if b"\x00" in data[:4096]:
        raise CorruptFileError("El archivo de la lista está dañado o no es un CSV de texto.")
    if suffix not in {".csv", ".txt", ""}:
        raise InvalidListFileError("Use un archivo CSV UTF-8 o un Excel .xlsx.")
    return "csv"


def _parse_csv(data: bytes) -> ParsedTable:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidListFileError(
            "No se pudo leer el CSV. Guárdelo con codificación UTF-8 e intente de nuevo."
        ) from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise InvalidListFileError("El archivo está vacío.")
    header_line = text.split("\n", 1)[0]
    delimiter = ","
    if header_line.count(";") > header_line.count(","):
        delimiter = ";"
    elif header_line.count("\t") > header_line.count(","):
        delimiter = "\t"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_rows = [list(row) for row in reader]
    return _table_from_rows(raw_rows, source="csv")


def _parse_xlsx(path: Path) -> ParsedTable:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        logger.info("Excel rechazado: %s", exc)
        raise CorruptFileError(
            "El archivo seleccionado no es un documento Excel válido o está dañado."
        ) from exc
    try:
        warnings: list[str] = []
        sheets = workbook.worksheets
        if not sheets:
            raise InvalidListFileError("El Excel no contiene hojas.")
        if len(sheets) > 1:
            warnings.append(
                f"Se utilizó la primera hoja ({sheets[0].title}). "
                f"El archivo contiene {len(sheets)} hojas."
            )
        raw_rows: list[list[str]] = []
        for row in sheets[0].iter_rows(values_only=True):
            raw_rows.append([_cell_str(value) for value in row])
    finally:
        workbook.close()
    table = _table_from_rows(raw_rows, source="xlsx")
    table.warnings.extend(warnings)
    return table


def _table_from_rows(raw_rows: list[list[str]], *, source: str) -> ParsedTable:
    content = [row for row in raw_rows if any(cell.strip() for cell in row)]
    if not content:
        raise InvalidListFileError("La lista no contiene participantes.")
    headers = _unique_headers(content[0])
    if not any(headers):
        raise InvalidListFileError("La primera fila no contiene nombres de columna.")
    width = len(headers)
    warnings: list[str] = []
    rows: list[list[str]] = []
    extra = False
    for raw in content[1:]:
        if len(raw) > width:
            extra = True
        padded = list(raw[:width]) + [""] * max(0, width - len(raw))
        rows.append([cell.strip() for cell in padded])
    if extra:
        warnings.append(
            "Algunas filas tienen más columnas que el encabezado. Las columnas extra se ignoraron."
        )
    if source == "csv" and rows and all(len(row) == 1 and row[0] for row in rows) and "," not in headers[0]:
        warnings.append("Solo se detectó una columna. Revise que el separador sea coma, punto y coma o tabulación.")
    return ParsedTable(headers=headers, rows=rows, warnings=warnings)


def _unique_headers(raw_headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, raw in enumerate(raw_headers, start=1):
        name = raw.strip() or f"Columna {index}"
        count = seen.get(name.casefold(), 0) + 1
        seen[name.casefold()] = count
        headers.append(name if count == 1 else f"{name} ({count})")
    return headers


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return str(value).strip()
