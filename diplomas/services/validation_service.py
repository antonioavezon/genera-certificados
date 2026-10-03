"""Validación de participantes y detección de duplicados, sin eliminar filas."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email

from diplomas.exceptions import InvalidListFileError
from diplomas.services.filename_service import preferred_filename

_CONTROL = re.compile(r"[\x00-\x1f\u200b-\u200f\u202a-\u202e\ufeff]")
_NAME_ALIASES = {
    "nombre",
    "nombres",
    "name",
    "first name",
    "firstname",
    "first_name",
    "given name",
}
_LAST_ALIASES = {
    "apellido",
    "apellidos",
    "last name",
    "lastname",
    "last_name",
    "surname",
    "family name",
}
_EMAIL_ALIASES = {
    "correo",
    "correo electronico",
    "email",
    "e-mail",
    "e mail",
    "mail",
}


@dataclass
class RowIssue:
    level: str
    code: str
    message: str


@dataclass
class ValidatedRow:
    row_number: int
    first_name: str
    last_name: str
    email: str
    status: str
    observations: str
    filename: str
    duplicate_kind: str
    issues: list[RowIssue] = field(default_factory=list)


def normalize_header(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.strip())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = re.sub(r"[_./]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    return {
        "first_name": _match(headers, _NAME_ALIASES),
        "last_name": _match(headers, _LAST_ALIASES),
        "email": _match(headers, _EMAIL_ALIASES),
    }


def validate_table(
    headers: list[str],
    rows: list[list[str]],
    mapping: dict[str, str],
    *,
    require_last_name: bool,
) -> list[ValidatedRow]:
    first_column = mapping.get("first_name") or ""
    last_column = mapping.get("last_name") or ""
    email_column = mapping.get("email") or ""
    if not first_column or first_column not in headers:
        raise InvalidListFileError(
            "No se encontró una columna de nombre. Seleccione qué columna de la lista contiene el nombre."
        )
    indexes = {header: position for position, header in enumerate(headers)}
    validated: list[ValidatedRow] = []
    for offset, row in enumerate(rows):
        validated.append(
            _validate_row(
                row_number=offset + 1,
                row=row,
                indexes=indexes,
                first_column=first_column,
                last_column=last_column if last_column in indexes else "",
                email_column=email_column if email_column in indexes else "",
                require_last_name=require_last_name,
            )
        )
    return _finalize(validated)


def validate_people(
    people: list[tuple[int, str, str, str]],
    *,
    require_last_name: bool,
) -> list[ValidatedRow]:
    """Valida participantes ya guardados, con numeración desde 1."""
    validated = [
        _validate_fields(row_number, first_name, last_name, email, require_last_name)
        for row_number, first_name, last_name, email in people
    ]
    return _finalize(validated)


def _validate_row(
    *,
    row_number: int,
    row: list[str],
    indexes: dict[str, int],
    first_column: str,
    last_column: str,
    email_column: str,
    require_last_name: bool,
) -> ValidatedRow:
    return _validate_fields(
        row_number,
        _cell(row, indexes, first_column),
        _cell(row, indexes, last_column) if last_column else "",
        _cell(row, indexes, email_column) if email_column else "",
        require_last_name,
    )


def _validate_fields(
    row_number: int,
    first_name: str,
    last_name: str,
    email: str,
    require_last_name: bool,
) -> ValidatedRow:
    issues: list[RowIssue] = []
    first = _clean_person(first_name, issues, "el nombre")
    last = _clean_person(last_name, issues, "el apellido")
    email = email.strip()
    if not first and not last and not email:
        return ValidatedRow(
            row_number=row_number,
            first_name="",
            last_name="",
            email="",
            status="error",
            observations="",
            filename="",
            duplicate_kind="",
            issues=[RowIssue("error", "empty", "La fila está completamente vacía.")],
        )
    if not first:
        issues.append(RowIssue("error", "empty-name", "El nombre está vacío."))
    if require_last_name and not last:
        issues.append(RowIssue("error", "empty-last-name", "El apellido está vacío."))
    if email and not _email_is_valid(email):
        issues.append(
            RowIssue(
                "warning",
                "invalid-email",
                "El correo no tiene un formato válido. El diploma puede generarse, pero no se enviará.",
            )
        )
    filename = ""
    if first:
        filename, shorten_warning = preferred_filename(first, last)
        if shorten_warning:
            issues.append(RowIssue("warning", "filename-length", shorten_warning))
    return ValidatedRow(
        row_number=row_number,
        first_name=first,
        last_name=last,
        email=email,
        status="valid",
        observations="",
        filename=filename,
        duplicate_kind="",
        issues=issues,
    )


def _finalize(rows: list[ValidatedRow]) -> list[ValidatedRow]:
    _mark_duplicates(rows)
    for item in rows:
        errors = [issue for issue in item.issues if issue.level == "error"]
        warnings = [issue for issue in item.issues if issue.level == "warning"]
        if errors:
            item.status = "error"
        elif warnings:
            item.status = "warning"
        else:
            item.status = "valid"
        item.observations = " ".join(issue.message for issue in item.issues)
        item.duplicate_kind = ",".join(dict.fromkeys(issue.code for issue in item.issues if issue.code))
    return rows


def _mark_duplicates(rows: list[ValidatedRow]) -> None:
    exact: dict[tuple[str, str, str], list[ValidatedRow]] = {}
    by_name: dict[tuple[str, str], list[ValidatedRow]] = {}
    by_email: dict[str, list[ValidatedRow]] = {}
    by_file: dict[str, list[ValidatedRow]] = {}
    for row in rows:
        if row.first_name or row.last_name:
            by_name.setdefault((_norm(row.first_name), _norm(row.last_name)), []).append(row)
        if row.first_name:
            exact.setdefault((_norm(row.first_name), _norm(row.last_name), row.email.casefold()), []).append(row)
        if row.email:
            by_email.setdefault(row.email.casefold(), []).append(row)
        if row.filename:
            by_file.setdefault(row.filename, []).append(row)

    for group in exact.values():
        usable = [row for row in group if row.first_name]
        if len(usable) < 2:
            continue
        first = usable[0]
        others = ", ".join(str(row.row_number) for row in usable[1:])
        first.issues.append(
            RowIssue(
                "warning",
                "exact",
                f"La misma persona está repetida en las filas {others}. Solo se generará el primer diploma.",
            )
        )
        for row in usable[1:]:
            row.issues.append(
                RowIssue(
                    "error",
                    "exact",
                    f"Persona repetida de la fila {first.row_number}. No se generará un diploma duplicado.",
                )
            )

    for group in by_name.values():
        usable = [row for row in group if row.first_name and row.last_name]
        emails = {row.email.casefold() for row in usable}
        if len(usable) < 2 or len(emails) < 2:
            continue
        listed = ", ".join(str(row.row_number) for row in usable)
        for row in usable:
            row.issues.append(
                RowIssue(
                    "warning",
                    "same-name",
                    f"Mismo nombre y apellido en las filas {listed}, con correos distintos.",
                )
            )

    for group in by_email.values():
        names = {(_norm(row.first_name), _norm(row.last_name)) for row in group}
        if len(group) < 2 or len(names) < 2:
            continue
        listed = ", ".join(str(row.row_number) for row in group)
        for row in group:
            row.issues.append(
                RowIssue(
                    "warning",
                    "same-email",
                    f"El mismo correo aparece en las filas {listed} con nombres distintos.",
                )
            )

    for filename, group in by_file.items():
        usable = [row for row in group if row.filename]
        if len(usable) < 2:
            continue
        listed = ", ".join(str(row.row_number) for row in usable)
        for row in usable:
            row.issues.append(
                RowIssue(
                    "warning",
                    "filename",
                    f"El archivo resultante {filename} también corresponde a las filas {listed}.",
                )
            )


def email_is_valid(value: str) -> bool:
    return _email_is_valid(value)


def _email_is_valid(value: str) -> bool:
    try:
        validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        return False
    return True


def _clean_person(value: str, issues: list[RowIssue], label: str) -> str:
    if _CONTROL.search(value):
        issues.append(
            RowIssue(
                "warning",
                "control-chars",
                f"Se quitaron caracteres de control de {label}. Revise el registro.",
            )
        )
        value = _CONTROL.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def _cell(row: list[str], indexes: dict[str, int], column: str) -> str:
    if not column:
        return ""
    position = indexes.get(column)
    if position is None or position >= len(row):
        return ""
    return row[position]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _match(headers: list[str], aliases: set[str]) -> str:
    for header in headers:
        if normalize_header(header) in aliases:
            return header
    return ""
