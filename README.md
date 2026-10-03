# Genera certificados

Esta aplicación se crea para automatizar la generación y envío de certificados de agradecimiento a personas. En primera instancia, para miembros y voluntarios del PMI.

Permite tomar una lista, un motivo y una plantilla, producir un PDF por persona y, si el correo está configurado, enviarlo. El historial queda en el equipo. Un certificado ya enviado no se manda otra vez salvo que se pida de forma explícita.

Autor: Antonio Ralph Avezon Saavedra. Project Management Professional (PMP®), PMI Capítulo Santiago de Chile. Año 2026.

## Qué hace

- Carga una lista CSV o Excel y permite añadir, editar o borrar personas.
- Usa un motivo escrito en pantalla o cargado desde un archivo de texto.
- Usa una plantilla JPG, PNG o PDF. Si el PDF tiene varias páginas, se elige cuál usar.
- Dibuja el nombre y el motivo sobre la plantilla y guarda un PDF por persona.
- Muestra miniaturas de la lista, la plantilla, el motivo y la configuración.
- Envía el certificado por SMTP. Gmail usa una contraseña de aplicación, no la contraseña de la cuenta.
- Conserva el historial de cada lote y permite continuar envíos pendientes o reintentar fallidos.

La aplicación escucha solo en el propio equipo, en `http://127.0.0.1:8765`. No usa Docker, Redis, Celery, PostgreSQL ni cuentas de usuario en la pantalla principal.

## Qué no se publica

Este repositorio no incluye datos de uso:

- el archivo `.env`, con el servidor de correo y la contraseña;
- la base SQLite y la clave local de `data/`;
- los PDF de `generated/`;
- las listas y plantillas cargadas en `uploads/`;
- los registros de `logs/`, que pueden contener nombres.

Esos archivos se crean al usar la aplicación y quedan solo en el equipo. El archivo de ejemplo `.env.example` no trae contraseñas.

Los CSV de `tests/fixtures/` son personas ficticias, con correos `@example.com`. Las imágenes y los PDF de prueba no se suben: se regeneran con `python tests/build_fixtures.py`.

## Requisitos

- Python 3.12 o superior
- Pip

Se desarrolló y probó en Fedora Linux 43 (Workstation Edition), en 2026, con Python 3.12.14 dentro del entorno virtual. En esa versión de Fedora, `python3` puede ser más nuevo que 3.12. Si `python3 --version` no es 3.12, use `python3.12` para crear el entorno. No mezcle los paquetes del sistema con el entorno virtual.

También funciona en Windows. Outlook de escritorio es la única función exclusiva de Windows. Si no está, el resto de la aplicación sigue operando.

## Instalación en Fedora 43

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python tests/build_fixtures.py
```

En otra distribución Linux, si `python3` ya es 3.12 o superior:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python tests/build_fixtures.py
```

## Instalación en Windows

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python tests/build_fixtures.py
```

`pywin32` solo se instala en Windows, mediante el marcador de `requirements.txt`.

## Cómo ejecutarla

Para el uso habitual, levante Waitress:

```bash
python start.py
```

Eso crea las carpetas que falten, aplica migraciones, reúne los archivos estáticos y abre `http://127.0.0.1:8765`. Para no abrir el navegador: `python start.py --no-browser`.

Durante el desarrollo también puede usar `python manage.py runserver 127.0.0.1:8765`.

## Correo

Copie el ejemplo y complete solo lo que vaya a usar:

```bash
cp .env.example .env
```

En Windows: `copy .env.example .env`.

La contraseña vive en `.env`. No se guarda en la base ni se muestra en pantalla. Desde **Configurar / Correo** hay tres pantallas:

- **Gmail**: correo de la cuenta y contraseña de aplicación. El servidor queda en `smtp.gmail.com`, puerto 587 y TLS. La contraseña de aplicación se crea en la cuenta de Google, con la verificación en dos pasos activa.
- **Otro proveedor**: servidor, puerto, TLS o SSL, usuario y remitente.
- **Cuerpo del correo**: asunto y mensaje. `{nombre}` se reemplaza por el nombre y el apellido.

También se puede validar la conexión y enviar un correo de prueba.

## Uso

1. **Lista**: cargue un CSV UTF-8 o un Excel `.xlsx`, o añada personas una a una. Asocie las columnas Nombre, Apellido y Correo. El correo puede quedar vacío si solo va a generar archivos.
2. **Motivo**: escríbalo o cargue un TXT UTF-8. Cada salto de línea es una línea del certificado.
3. **Plantilla**: JPG, PNG o PDF.
4. **Configurar**: posición del nombre, posición del motivo, salida del PDF y correo. Las posiciones van en porcentaje. Las fuentes se leen de `fonts/` (TTF u OTF). DejaVu Sans va incluida.
5. **Generar**: revise la vista previa. Si un PDF ya existe, se pregunta si quiere otra copia. La respuesta inicial es no y el archivo original no se reemplaza. Si la respuesta es sí, se crea `nombre_1.pdf`, `nombre_2.pdf` y así sucesivamente.
6. **Historial**: filtre el lote, descargue el CSV de resultados o borre el historial. Borrar el historial no borra los PDF de la carpeta.

Los PDF se guardan en `generated/`. El nombre preferente es `nombre.apellido.pdf`, en minúsculas y sin acentos. Ejemplo: María José Pérez González produce `maria-jose.perez-gonzalez.pdf`.

## Envío

- Un correo ya enviado no se manda otra vez.
- **Continuar envíos pendientes** retoma los que no llegaron a enviarse.
- **Reintentar fallidos** solo toca los que fallaron y nunca se confirmaron.
- **Reenviar** es una acción explícita por persona.
- Un fallo de una persona no detiene al resto del lote.
- Cada PDF se escribe primero en `temp/` y solo se mueve cuando se pudo abrir.

## Carpetas

Al iniciar se crean, si faltan:

- `generated/` certificados PDF
- `uploads/` listas y plantillas, con nombres internos aleatorios
- `temp/` archivos temporales
- `logs/` registros de la aplicación, la generación y el correo
- `fonts/` fuentes TTF/OTF
- `data/` base SQLite y clave local

Si no hay permiso de escritura, la pantalla lo dice.

## Pruebas

```bash
python tests/build_fixtures.py
python manage.py test diplomas.tests
```

Cubren CSV, XLSX, archivos dañados, JPG, PNG, PDF de una página y de varias, nombres vacíos, correos inválidos, nombres largos, duplicados, colisiones de archivo, carpetas sin permiso, diplomas ya existentes, envío exitoso, envío fallido y Outlook ausente en Linux.

## Administración

El sitio de administración de Django está en `/admin/` y es opcional:

```bash
python manage.py createsuperuser
```

## Limitaciones

- La generación y el envío ocurren en la misma petición. No hay cola de tareas.
- El PDF contiene la plantilla y el texto ya dibujados como imagen, para que la vista previa y el archivo coincidan. El texto no queda seleccionable.
- No hay cuentas de usuario en la interfaz principal.
- El cuerpo del correo es texto plano.
- Hay una lista activa, una plantilla activa y un motivo a la vez. El historial de lotes anteriores se conserva.

## Licencia de la fuente incluida

`fonts/` incluye DejaVu Sans (regular, negrita, oblicua y negrita oblicua). La licencia está en `fonts/LICENSE-DejaVu.txt`.
