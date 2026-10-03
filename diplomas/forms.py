"""Formularios de la interfaz. La validación de negocio sigue en los servicios."""

from __future__ import annotations

import re

from django import forms
from django.core import validators

from diplomas.models import ApplicationSettings, CollisionPolicy, OverflowPolicy
from diplomas.services.font_service import available_fonts, font_exists
from diplomas.services.validation_service import email_is_valid, suggest_mapping

_HEX = re.compile(r"#[0-9A-F]{6}")


def _widgets(form: forms.BaseForm) -> None:
    for field in form.fields.values():
        css = field.widget.attrs.get("class", "")
        if isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs["class"] = f"{css} form-check-input".strip()
        elif isinstance(field.widget, (forms.Select, forms.RadioSelect)):
            field.widget.attrs["class"] = f"{css} form-select".strip()
        elif isinstance(field.widget, forms.FileInput):
            field.widget.attrs["class"] = f"{css} form-control".strip()
        else:
            field.widget.attrs["class"] = f"{css} form-control".strip()


class PercentField(forms.FloatField):
    """Muestra 0–100 en pantalla y guarda 0–1 en la base."""

    def __init__(self, **kwargs):
        kwargs.setdefault("localize", False)
        # Los límites son del porcentaje visible. Si se pasan a FloatField,
        # se aplican después de dividir por 100 y 80 queda por debajo de 5.
        self.percent_min = kwargs.pop("min_value", None)
        self.percent_max = kwargs.pop("max_value", None)
        super().__init__(**kwargs)
        if self.percent_min is not None:
            self.widget.attrs["min"] = self.percent_min
        if self.percent_max is not None:
            self.widget.attrs["max"] = self.percent_max
        self.widget.attrs["step"] = "0.1"

    def prepare_value(self, value):
        if value in (None, ""):
            return value
        if isinstance(value, str):
            return value.replace(",", ".")
        percent = round(float(value) * 100, 2)
        if percent == int(percent):
            return str(int(percent))
        return f"{percent:.2f}".rstrip("0").rstrip(".")

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(" ", "").replace(",", ".")
        number = super().to_python(value)
        if number is None:
            return None
        if self.percent_min is not None:
            validators.MinValueValidator(self.percent_min)(number)
        if self.percent_max is not None:
            validators.MaxValueValidator(self.percent_max)(number)
        return float(number) / 100.0


class ParticipantForm(forms.Form):
    first_name = forms.CharField(label="Nombre", max_length=200)
    last_name = forms.CharField(label="Apellido", max_length=200, required=False)
    email = forms.CharField(label="Correo", max_length=320, required=False)

    def __init__(self, *args, require_last_name: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["last_name"].required = require_last_name
        _widgets(self)


class SmtpSettingsForm(forms.Form):
    host = forms.CharField(label="Servidor", max_length=255)
    port = forms.IntegerField(label="Puerto", min_value=1, max_value=65535, initial=587)
    use_tls = forms.BooleanField(label="TLS", required=False, initial=True)
    use_ssl = forms.BooleanField(label="SSL", required=False)
    user = forms.CharField(
        label="Correo de Gmail",
        max_length=320,
        required=False,
        help_text="La cuenta que envía. En Gmail es el mismo correo del remitente.",
    )
    password = forms.CharField(
        label="Contraseña de aplicación",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="No es la contraseña normal de Gmail. Si la deja vacía, se conserva la ya guardada.",
    )
    sender = forms.CharField(
        label="Remitente",
        max_length=320,
        required=False,
        help_text="Si lo deja vacío, se usa el correo de Gmail.",
    )
    test_to = forms.CharField(
        label="Correo de prueba",
        max_length=320,
        required=False,
        help_text="Si lo deja vacío, la prueba se envía al correo de Gmail.",
    )

    def __init__(self, *args, gmail: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if not gmail:
            self.fields["user"].label = "Usuario"
            self.fields["user"].help_text = "Cuenta del servidor. Puede quedar vacía."
            self.fields["password"].label = "Contraseña"
            self.fields["password"].help_text = "Si la deja vacía, se conserva la ya guardada."
            self.fields["sender"].help_text = "Dirección que aparece como remitente."
            self.fields["test_to"].help_text = "Si lo deja vacío, la prueba se envía al remitente."
        _widgets(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("use_tls") and cleaned.get("use_ssl"):
            raise forms.ValidationError("Active solo una opción: TLS o SSL.")
        host = (cleaned.get("host") or "").strip().lower()
        user = (cleaned.get("user") or "").strip()
        sender = (cleaned.get("sender") or "").strip()
        password = cleaned.get("password") or ""
        if host == "smtp.gmail.com":
            password = password.replace(" ", "")
        if not sender and email_is_valid(user):
            sender = user
        if host == "smtp.gmail.com" and not email_is_valid(user):
            self.add_error("user", "Escriba el correo de Gmail.")
        elif sender and not email_is_valid(sender):
            self.add_error("sender", "El remitente no tiene un formato de correo válido.")
        elif not sender:
            self.add_error("sender", "Escriba el remitente. En Gmail es el mismo correo.")
        test_to = (cleaned.get("test_to") or "").strip()
        if test_to and not email_is_valid(test_to):
            self.add_error("test_to", "El correo de prueba no tiene un formato válido.")
        cleaned["user"] = user
        cleaned["sender"] = sender
        cleaned["password"] = password
        return cleaned


class UploadListForm(forms.Form):
    data_file = forms.FileField(label="Archivo CSV o Excel")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class MotiveForm(forms.Form):
    text = forms.CharField(
        label="Motivo",
        required=False,
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text="Cada salto de línea es una línea independiente en el diploma.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class MotiveUploadForm(forms.Form):
    motive_file = forms.FileField(label="Archivo de texto UTF-8")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class TemplateUploadForm(forms.Form):
    template_file = forms.FileField(label="Plantilla JPG, PNG o PDF")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class PageSelectForm(forms.Form):
    page = forms.IntegerField(label="Página", min_value=1)

    def __init__(self, *args, page_count: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["page"].max_value = page_count
        self.fields["page"].widget.attrs["max"] = page_count
        _widgets(self)


def build_mapping_form(headers: list[str], data=None):
    choices = [(header, header) for header in headers]
    optional = [("", "— No usar —"), *choices]
    suggested = suggest_mapping(headers)

    class MappingForm(forms.Form):
        first_name = forms.ChoiceField(label="Nombre", choices=choices)
        last_name = forms.ChoiceField(label="Apellido", choices=optional, required=False)
        email = forms.ChoiceField(
            label="Correo",
            choices=optional,
            required=False,
            help_text="Puede quedar vacío si solo va a generar diplomas. Para enviar, el correo es obligatorio.",
        )

        def clean(self):
            cleaned = super().clean()
            chosen = [cleaned.get("first_name"), cleaned.get("last_name"), cleaned.get("email")]
            chosen = [item for item in chosen if item]
            if len(chosen) != len(set(chosen)):
                raise forms.ValidationError("Cada dato debe usar una columna distinta.")
            return cleaned

    _widgets(MappingForm())
    for field in MappingForm.base_fields.values():
        field.widget.attrs["class"] = "form-select"
    if data is not None:
        return MappingForm(data)
    return MappingForm(initial=suggested)


NAME_LAYOUT_FIELDS = (
    "name_x",
    "name_y",
    "name_font",
    "name_font_size",
    "name_min_font_size",
    "name_max_font_size",
    "name_color",
    "name_bold",
    "name_italic",
    "name_align",
    "name_max_width",
    "name_uppercase",
    "name_autofit",
    "name_two_lines",
    "name_overflow_policy",
)
MOTIVE_LAYOUT_FIELDS = (
    "motive_x",
    "motive_y",
    "motive_font",
    "motive_font_size",
    "motive_color",
    "motive_bold",
    "motive_italic",
    "motive_align",
    "motive_line_spacing",
    "motive_max_width",
)
OUTPUT_LAYOUT_FIELDS = (
    "dpi",
    "safe_margin",
    "collision_policy",
    "require_last_name",
)
EMAIL_LAYOUT_FIELDS = (
    "email_provider",
    "email_subject",
    "email_body",
)
EMAIL_BODY_FIELDS = (
    "email_subject",
    "email_body",
)


def layout_section(data, instance, names):
    """Formulario de configuración con solo los campos de una vista."""
    form = LayoutForm(data, instance=instance) if data is not None else LayoutForm(instance=instance)
    allowed = set(names)
    for key in list(form.fields):
        if key not in allowed:
            del form.fields[key]
    return form


class LayoutForm(forms.ModelForm):
    name_x = PercentField(label="Posición X", min_value=0, max_value=100, help_text="Porcentaje desde la izquierda.")
    name_y = PercentField(label="Posición Y", min_value=0, max_value=100, help_text="Porcentaje desde arriba.")
    name_max_width = PercentField(label="Ancho máximo", min_value=5, max_value=100)
    motive_x = PercentField(label="Posición X", min_value=0, max_value=100)
    motive_y = PercentField(label="Posición Y inicial", min_value=0, max_value=100)
    motive_max_width = PercentField(label="Ancho máximo", min_value=5, max_value=100)
    safe_margin = PercentField(
        label="Margen de seguridad",
        min_value=0,
        max_value=20,
        help_text="Solo avisa si una posición queda más cerca del borde que este margen.",
    )

    class Meta:
        model = ApplicationSettings
        fields = [
            "name_x",
            "name_y",
            "name_font",
            "name_font_size",
            "name_min_font_size",
            "name_max_font_size",
            "name_color",
            "name_bold",
            "name_italic",
            "name_align",
            "name_max_width",
            "name_uppercase",
            "name_autofit",
            "name_two_lines",
            "name_overflow_policy",
            "motive_x",
            "motive_y",
            "motive_font",
            "motive_font_size",
            "motive_color",
            "motive_bold",
            "motive_italic",
            "motive_align",
            "motive_line_spacing",
            "motive_max_width",
            "dpi",
            "safe_margin",
            "collision_policy",
            "require_last_name",
            "email_subject",
            "email_body",
            "email_provider",
        ]
        labels = {
            "name_font": "Fuente",
            "name_font_size": "Tamaño",
            "name_min_font_size": "Tamaño mínimo",
            "name_max_font_size": "Tamaño máximo",
            "name_color": "Color",
            "name_bold": "Negrita",
            "name_italic": "Cursiva",
            "name_align": "Alineación",
            "name_uppercase": "Mayúsculas",
            "name_autofit": "Ajuste automático",
            "name_two_lines": "Permitir dos líneas si no cabe",
            "name_overflow_policy": "Si el nombre no cabe",
            "motive_font": "Fuente",
            "motive_font_size": "Tamaño",
            "motive_color": "Color",
            "motive_bold": "Negrita",
            "motive_italic": "Cursiva",
            "motive_align": "Alineación",
            "motive_line_spacing": "Interlineado",
            "dpi": "Resolución (DPI)",
            "collision_policy": "Si dos personas generan el mismo archivo",
            "require_last_name": "El apellido es obligatorio",
            "email_subject": "Asunto",
            "email_body": "Cuerpo del mensaje",
            "email_provider": "Proveedor",
        }
        help_texts = {
            "name_font_size": "En puntos tipográficos. Se convierte a píxeles según la resolución.",
            "name_autofit": "Si el nombre no cabe, el tamaño baja de a un punto hasta el mínimo.",
            "motive_line_spacing": "1,35 significa un 135 % del tamaño de la fuente entre líneas.",
            "collision_policy": "Por defecto se bloquea el segundo. El sufijo _2, _3 solo se usa si lo elige aquí.",
            "email_body": "Puede usar {nombre}. Se reemplaza por el nombre y el apellido.",
            "email_subject": "También acepta {nombre}.",
            "dpi": "300 es una resolución adecuada para imprimir.",
        }
        widgets = {
            "email_body": forms.Textarea(attrs={"rows": 8}),
            "name_color": forms.TextInput(attrs={"pattern": "#[0-9A-Fa-f]{6}", "maxlength": "7"}),
            "motive_color": forms.TextInput(attrs={"pattern": "#[0-9A-Fa-f]{6}", "maxlength": "7"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fonts = [(name, name) for name in available_fonts()] or [("", "No hay fuentes en la carpeta fonts")]
        for field_name in ("name_font", "motive_font"):
            current = getattr(self.instance, field_name, "")
            choices = list(fonts)
            if current and current not in dict(choices):
                choices.append((current, f"{current} (no disponible)"))
            self.fields[field_name].widget = forms.Select(choices=choices)
        self.fields["name_align"].widget = forms.Select(
            choices=[("left", "Izquierda"), ("center", "Centro"), ("right", "Derecha")]
        )
        self.fields["motive_align"].widget = forms.Select(
            choices=[("left", "Izquierda"), ("center", "Centro"), ("right", "Derecha")]
        )
        self.fields["email_provider"].widget = forms.Select(
            choices=[
                ("none", "Sin correo"),
                ("smtp", "SMTP"),
                ("outlook", "Outlook Desktop (solo Windows)"),
            ]
        )
        self.fields["collision_policy"].widget = forms.Select(choices=CollisionPolicy.choices)
        self.fields["name_overflow_policy"].widget = forms.Select(choices=OverflowPolicy.choices)
        for name in (
            "name_font_size",
            "name_min_font_size",
            "name_max_font_size",
            "motive_font_size",
            "dpi",
            "motive_line_spacing",
        ):
            self.fields[name].localize = False
        _widgets(self)

    def clean_name_color(self):
        return _hex(self.cleaned_data["name_color"], "nombre")

    def clean_motive_color(self):
        return _hex(self.cleaned_data["motive_color"], "motivo")

    def clean_name_font(self):
        return _font(self.cleaned_data["name_font"])

    def clean_motive_font(self):
        return _font(self.cleaned_data["motive_font"])

    def clean(self):
        cleaned = super().clean()
        size = cleaned.get("name_font_size")
        minimum = cleaned.get("name_min_font_size")
        maximum = cleaned.get("name_max_font_size")
        if size and minimum and minimum > size:
            self.add_error("name_min_font_size", "El tamaño mínimo no puede ser mayor que el tamaño elegido.")
        if size and maximum and size > maximum:
            self.add_error("name_font_size", "El tamaño no puede ser mayor que el tamaño máximo.")
        dpi = cleaned.get("dpi")
        if dpi is not None and not 72 <= dpi <= 600:
            self.add_error("dpi", "La resolución debe estar entre 72 y 600 DPI.")
        spacing = cleaned.get("motive_line_spacing")
        if spacing is not None and not 0.8 <= spacing <= 3:
            self.add_error("motive_line_spacing", "El interlineado debe estar entre 0,8 y 3.")
        return cleaned


def _hex(value: str, label: str) -> str:
    text = (value or "").strip().upper()
    if not _HEX.fullmatch(text):
        raise forms.ValidationError(
            f"El color del {label} debe tener formato hexadecimal, por ejemplo #F26522."
        )
    return text


def _font(value: str) -> str:
    if not font_exists(value):
        raise forms.ValidationError("La fuente seleccionada no está disponible.")
    return value
