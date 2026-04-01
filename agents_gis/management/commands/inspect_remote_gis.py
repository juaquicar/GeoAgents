"""
Management command: inspect_remote_gis

Conecta a la BD GIS configurada (por defecto el alias 'gis_remote',
o el indicado con --db-alias), introspecciona las tablas con columnas
de geometría PostGIS y genera el catálogo de capas AGENTS_GIS_LAYERS.

Uso:
    # Inspeccionar y mostrar en pantalla
    python manage.py inspect_remote_gis

    # Guardar automáticamente en gis_layers_catalog.json
    python manage.py inspect_remote_gis --save

    # Usar un alias de BD distinto
    python manage.py inspect_remote_gis --db-alias gis_remote --save

    # Filtrar solo ciertas tablas (por esquema)
    python manage.py inspect_remote_gis --schema public --save

El fichero gis_layers_catalog.json resultante se coloca en BASE_DIR y
settings.py lo carga automáticamente si existe.
"""

import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

# Tipos de geometría PostGIS → geometry_kind del catálogo
_GEOM_KIND_MAP = {
    "point": "point",
    "multipoint": "point",
    "linestring": "line",
    "multilinestring": "line",
    "linestringz": "line",
    "multilinestringz": "line",
    "polygon": "polygon",
    "multipolygon": "polygon",
    "geometry": "point",          # fallback genérico
    "geometrycollection": "point",
}

# Tipos de columna SQL que excluimos del catálogo de fields
_SKIP_TYPES = {
    "geometry", "geography", "bytea", "oid", "xid", "cid", "tid",
}

# Columnas de sistema PostgreSQL que ignoramos
_SYSTEM_COLS = {
    "tableoid", "cmax", "xmax", "cmin", "xmin", "ctid",
}


def _fetchall_dict(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _infer_id_col(columns: list[dict]) -> str:
    """Devuelve el nombre de la columna de clave primaria / id."""
    for col in columns:
        if col["name"] in ("id", "gid", "ogc_fid", "objectid", "fid"):
            return col["name"]
    # Primer entero que no sea geométrico
    for col in columns:
        if col["data_type"] in ("integer", "bigint", "smallint", "serial", "bigserial"):
            return col["name"]
    return "id"


def _infer_geometry_kind(geom_type: str) -> str:
    key = geom_type.lower().replace("multi", "multi")
    return _GEOM_KIND_MAP.get(key, "point")


def _inspect_tables(cursor, schema: str) -> list[dict]:
    """Lista tablas con columnas de geometría en el esquema dado."""
    cursor.execute(
        """
        SELECT
            f_table_schema  AS schema,
            f_table_name    AS table_name,
            f_geometry_column AS geom_col,
            type            AS geom_type,
            srid
        FROM geometry_columns
        WHERE f_table_schema = %s
        ORDER BY f_table_name
        """,
        [schema],
    )
    return _fetchall_dict(cursor)


def _inspect_columns(cursor, schema: str, table: str) -> list[dict]:
    """Lista columnas de una tabla (excluye geométricas y de sistema)."""
    cursor.execute(
        """
        SELECT
            column_name AS name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name   = %s
        ORDER BY ordinal_position
        """,
        [schema, table],
    )
    rows = _fetchall_dict(cursor)
    return [
        r for r in rows
        if r["name"] not in _SYSTEM_COLS
        and r["data_type"].lower() not in _SKIP_TYPES
    ]


class Command(BaseCommand):
    help = "Inspecciona la PostGIS remota y genera el catálogo de capas GIS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--db-alias",
            default="gis_remote",
            help="Alias de BD Django a usar (default: gis_remote). "
                 "Si no existe, usa 'default'.",
        )
        parser.add_argument(
            "--schema",
            default=None,
            help="Esquema PostgreSQL a inspeccionar (default: AGENTS_GIS_SCHEMA o 'public').",
        )
        parser.add_argument(
            "--save",
            action="store_true",
            default=False,
            help="Guarda el resultado en BASE_DIR/gis_layers_catalog.json.",
        )
        parser.add_argument(
            "--include",
            nargs="*",
            metavar="TABLE",
            help="Incluir solo estas tablas (puede usarse varias veces).",
        )
        parser.add_argument(
            "--exclude",
            nargs="*",
            metavar="TABLE",
            help="Excluir estas tablas del catálogo.",
        )

    def handle(self, *args, **options):
        alias = options["db_alias"]
        schema = options["schema"] or getattr(settings, "AGENTS_GIS_SCHEMA", "public")
        include = set(options.get("include") or [])
        exclude = set(options.get("exclude") or [])

        # Si el alias no existe en DATABASES, caemos a 'default'
        if alias not in settings.DATABASES:
            self.stderr.write(
                self.style.WARNING(
                    f"Alias '{alias}' no encontrado en DATABASES. "
                    f"Usando 'default'."
                )
            )
            alias = "default"

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Inspeccionando BD '{alias}' · esquema '{schema}' ..."
            )
        )

        conn = connections[alias]

        try:
            with conn.cursor() as cur:
                tables = _inspect_tables(cur, schema)
        except Exception as exc:
            raise CommandError(
                f"Error al conectar / inspeccionar la BD '{alias}': {exc}"
            ) from exc

        if not tables:
            self.stderr.write(
                self.style.WARNING(
                    f"No se encontraron tablas con geometría en el esquema '{schema}'."
                )
            )
            return

        catalog = []
        for tbl in tables:
            table_name = tbl["table_name"]

            if include and table_name not in include:
                continue
            if table_name in exclude:
                continue

            with conn.cursor() as cur:
                cols = _inspect_columns(cur, schema, table_name)

            geom_col = tbl["geom_col"]
            geom_type = tbl["geom_type"] or "GEOMETRY"
            geometry_kind = _infer_geometry_kind(geom_type)

            # Campos útiles (sin la columna de geometría)
            data_cols = [
                c["name"] for c in cols
                if c["name"] != geom_col
            ]

            id_col = _infer_id_col(
                [c for c in cols if c["name"] != geom_col]
            )

            # fields: todos excepto id y geom
            fields = [c for c in data_cols if c != id_col]

            entry = {
                "name": table_name,
                "table": table_name,
                "geom_col": geom_col,
                "id_col": id_col,
                "fields": fields,
                "filter_fields": fields,
                "geometry_kind": geometry_kind,
                "srid": int(tbl["srid"]) if tbl.get("srid") else 4326,
                "geom_type": geom_type,
            }

            if schema != "public":
                entry["schema"] = schema

            catalog.append(entry)

            self.stdout.write(
                f"  {self.style.SUCCESS('✔')} {table_name:40s} "
                f"{geom_type:<20s} → {geometry_kind}"
            )

        self.stdout.write(
            f"\nTotal: {len(catalog)} capa(s) encontrada(s)."
        )

        # Mostrar el catálogo como JSON
        catalog_json = json.dumps(catalog, indent=2, ensure_ascii=False)
        self.stdout.write("\n--- AGENTS_GIS_LAYERS generado ---")
        self.stdout.write(catalog_json)

        if options["save"]:
            output_path = settings.BASE_DIR / "gis_layers_catalog.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2, ensure_ascii=False)
            self.stdout.write(
                self.style.SUCCESS(f"\nCatálogo guardado en: {output_path}")
            )
            self.stdout.write(
                "Reinicia el servidor para que settings.py cargue el nuevo catálogo."
            )
