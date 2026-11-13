"""Sweep de acentos y enes en los textos visibles del backoffice.

Corrige unicamente literales de cadena (comillas simples, dobles o backticks)
para no tocar identificadores, claves de query (``pais``, ``categoria``) ni
valores de enum del backend.

Uso::

    python scripts/fix_backoffice_accents.py --dry-run
    python scripts/fix_backoffice_accents.py --apply
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BACKOFFICE_DIR = Path(__file__).resolve().parent.parent / "uis" / "backoffice"

# Formas incorrectas -> forma correcta para el texto visible.
WORDS = {
    "contrasena": "contraseña",
    "Contrasena": "Contraseña",
    "sesion": "sesión",
    "Sesion": "Sesión",
    "autenticacion": "autenticación",
    "Autenticacion": "Autenticación",
    "autorizacion": "autorización",
    "conexion": "conexión",
    "configuracion": "configuración",
    "Configuracion": "Configuración",
    "recuperacion": "recuperación",
    "Recuperacion": "Recuperación",
    "confirmacion": "confirmación",
    "Confirmacion": "Confirmación",
    "validacion": "validación",
    "Validacion": "Validación",
    "informacion": "información",
    "Informacion": "Información",
    "direccion": "dirección",
    "Direccion": "Dirección",
    "telefono": "teléfono",
    "Telefono": "Teléfono",
    "metricas": "métricas",
    "Metricas": "Métricas",
    "metrica": "métrica",
    "estadisticas": "estadísticas",
    "estadistica": "estadística",
    "gestion": "gestión",
    "Gestion": "Gestión",
    "numero": "número",
    "Numero": "Número",
    "almacen": "almacén",
    "almacenes": "almacenes",
    "valido": "válido",
    "Valido": "Válido",
    "valida": "válida",
    "invalido": "inválido",
    "Invalido": "Inválido",
    "invalida": "inválida",
    "Ocurrio": "Ocurrió",
    "ocurrio": "ocurrió",
    "categoria": "categoría",
    "Categoria": "Categoría",
    "categorias": "categorías",
    "descripcion": "descripción",
    "Descripcion": "Descripción",
    "titulo": "título",
    "Titulo": "Título",
    "ultima": "última",
    "Ultima": "Última",
    "logistica": "logística",
    "Logistica": "Logística",
    "analisis": "análisis",
    "Analisis": "Análisis",
    "operacion": "operación",
    "Operacion": "Operación",
    "revision": "revisión",
    "Revision": "Revisión",
    "accion": "acción",
    "Accion": "Acción",
    "suspension": "suspensión",
    "cancelacion": "cancelación",
    "exito": "éxito",
    "periodo": "período",
    "envios": "envíos",
    "devolucion": "devolución",
    "notificacion": "notificación",
    "Notificacion": "Notificación",
    "pagina": "página",
    "Pagina": "Página",
    "codigo": "código",
    "Codigo": "Código",
    "pais": "país",
    "Pais": "País",
    "proximo": "próximo",
    "proxima": "próxima",
    "tambien": "también",
    "aqui": "aquí",
    "asi": "así",
    "razon": "razón",
    "version": "versión",
    "Version": "Versión",
    "sancion": "sanción",
    "Anios": "Años",
    "anios": "años",
    "maximo": "máximo",
    "minimo": "mínimo",
    "tecnica": "técnica",
    "Tecnica": "Técnica",
    "tecnico": "técnico",
    "invalidas": "inválidas",
    "invalidos": "inválidos",
    "encontro": "encontró",
    "despues": "después",
    "eliminara": "eliminará",
    "sera": "será",
    "esta registrada": "está registrada",
    "Deseas": "¿Deseas",
}

# Literales que NO deben acentuarse nunca: valores de enum del backend.
PROTECTED_EXACT = {
    "Almacen",
    "Ultima_Milla",
    "Logistica_Inversa",
    "Tecnologia",
}

# Claves de query/payload que viajan en la peticion HTTP y no se acentuan.
PROTECTED_SUBSTRINGS = (
    'params.set("pais"',
    "params.set('pais'",
    'params.set("categoria"',
    "params.set('categoria'",
)

STRING_LITERAL = re.compile(r'(?P<quote>["\'`])(?P<body>(?:\\.|(?!\1).)*?)(?P=quote)')
# Texto suelto entre etiquetas JSX: >Texto<  (una sola linea, sin llaves).
JSX_TEXT = re.compile(r"(?<=>)(?P<body>[^<>{}]*\S[^<>{}]*?)(?=<)")


def _should_skip(body: str, raw: str) -> bool:
    """Descarta literales que son identificadores, rutas o claves tecnicas."""
    stripped = body.strip()
    if not stripped:
        return True
    if stripped in PROTECTED_EXACT:
        return True
    if any(token in raw for token in PROTECTED_SUBSTRINGS):
        return True
    # Valores con guion bajo son enums snake_case del backend.
    if "_" in stripped and " " not in stripped:
        return True
    # Rutas, imports, URLs y extensiones.
    if stripped.startswith(("/", "@", "http", "./", "../", ".")):
        return True
    if "/" in stripped and " " not in stripped:
        return True
    # Identificadores "tecnicos" sin espacios ni mayusculas iniciales.
    if re.fullmatch(r"[a-z0-9_\-]+", stripped):
        return True
    return False


def _fix_body(body: str) -> str:
    return re.sub(
        r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+",
        lambda match: WORDS.get(match.group(0), match.group(0)),
        body,
    )


def process_file(path: Path, apply: bool) -> list[tuple[int, str, str]]:
    original = path.read_text(encoding="utf-8")
    changes: list[tuple[int, str, str]] = []

    def replace_literal(match: re.Match[str]) -> str:
        quote = match.group("quote")
        body = match.group("body")

        if _should_skip(body, match.group(0)):
            return match.group(0)

        fixed = _fix_body(body)
        if fixed == body:
            return match.group(0)

        line_number = original[: match.start()].count("\n") + 1
        changes.append((line_number, body, fixed))
        return f"{quote}{fixed}{quote}"

    updated = STRING_LITERAL.sub(replace_literal, original)

    # Segunda pasada: texto suelto entre etiquetas JSX ("<p>Metricas</p>"),
    # que no esta entrecomillado y por tanto la pasada anterior no toca.
    def replace_jsx_text(match: re.Match[str]) -> str:
        body = match.group("body")
        fixed = _fix_body(body)
        if fixed == body:
            return match.group(0)
        line_number = updated[: match.start()].count("\n") + 1
        changes.append((line_number, body.strip(), fixed.strip()))
        return fixed

    updated = JSX_TEXT.sub(replace_jsx_text, updated)

    if apply and changes and updated != original:
        path.write_text(updated, encoding="utf-8")

    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Escribe los cambios.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra los cambios.")
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    total = 0
    patterns = ("*.tsx", "*.ts")

    for pattern in patterns:
        for path in sorted(BACKOFFICE_DIR.rglob(pattern)):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            if path.name.endswith(".d.ts"):
                continue

            changes = process_file(path, apply)
            if not changes:
                continue

            print(f"\n{path.relative_to(BACKOFFICE_DIR)}")
            for line_number, before, after in changes:
                print(f"  L{line_number}: {before} -> {after}")
            total += len(changes)

    print(f"\n{'Aplicados' if apply else 'Detectados'}: {total} cambios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
