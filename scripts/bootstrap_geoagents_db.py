#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path

import django
from django.db import connection, transaction


# ---------------------------------------------------------
# Bootstrap Django
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoagents.settings")
django.setup()


from agents_core.models import Agent  # noqa: E402


AGENT_NAME = "demo-gis-agent"


AGENT_SYSTEM_PROMPT = """
Eres un agente GIS de demostración.
Tu objetivo es analizar contexto espacial, consultar capas y trazar rutas de red
usando exclusivamente las tools permitidas.
Responde en español.
""".strip()


VECTOR_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS demo_points (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    the_geom geometry(Point, 4326)
);

ALTER TABLE demo_points
    ADD COLUMN IF NOT EXISTS category VARCHAR(50);

CREATE INDEX IF NOT EXISTS demo_points_geom_gix
ON demo_points
USING GIST (the_geom);


CREATE TABLE IF NOT EXISTS demo_lines (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    the_geom geometry(LineString, 4326)
);

ALTER TABLE demo_lines
    ADD COLUMN IF NOT EXISTS category VARCHAR(50);

CREATE INDEX IF NOT EXISTS demo_lines_geom_gix
ON demo_lines
USING GIST (the_geom);


CREATE TABLE IF NOT EXISTS demo_polygons (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    the_geom geometry(Polygon, 4326)
);

ALTER TABLE demo_polygons
    ADD COLUMN IF NOT EXISTS category VARCHAR(50);

CREATE INDEX IF NOT EXISTS demo_polygons_geom_gix
ON demo_polygons
USING GIST (the_geom);
"""

RESET_SQL = """
TRUNCATE TABLE demo_points RESTART IDENTITY;
TRUNCATE TABLE demo_lines RESTART IDENTITY;
TRUNCATE TABLE demo_polygons RESTART IDENTITY;
"""


SEED_SQL = """
-- ------------------------------------------------------
-- Polígonos demo
-- ------------------------------------------------------
INSERT INTO demo_polygons (name, category, the_geom) VALUES
(
    'Zona Norte',
    'coverage',
    ST_GeomFromText(
        'POLYGON((
            -6.0600 37.3260,
            -6.0530 37.3260,
            -6.0530 37.3300,
            -6.0600 37.3300,
            -6.0600 37.3260
        ))',
        4326
    )
),
(
    'Zona Sur',
    'coverage',
    ST_GeomFromText(
        'POLYGON((
            -6.0600 37.3200,
            -6.0530 37.3200,
            -6.0530 37.3260,
            -6.0600 37.3260,
            -6.0600 37.3200
        ))',
        4326
    )
);

-- ------------------------------------------------------
-- Líneas demo (red)
-- Ojo: conectadas extremo a extremo para network_trace
-- ------------------------------------------------------
INSERT INTO demo_lines (name, category, the_geom) VALUES
(
    'Tramo 1',
    'fiber',
    ST_GeomFromText(
        'LINESTRING(-6.0595 37.3210, -6.0585 37.3220)',
        4326
    )
),
(
    'Tramo 2',
    'fiber',
    ST_GeomFromText(
        'LINESTRING(-6.0585 37.3220, -6.0570 37.3235)',
        4326
    )
),
(
    'Tramo 3',
    'fiber',
    ST_GeomFromText(
        'LINESTRING(-6.0570 37.3235, -6.0555 37.3250)',
        4326
    )
),
(
    'Tramo 4',
    'fiber',
    ST_GeomFromText(
        'LINESTRING(-6.0555 37.3250, -6.0540 37.3270)',
        4326
    )
);

-- ------------------------------------------------------
-- Puntos demo
-- ------------------------------------------------------
INSERT INTO demo_points (name, category, the_geom) VALUES
(
    'CTO-01',
    'cto',
    ST_GeomFromText('POINT(-6.0592 37.3212)', 4326)
),
(
    'CTO-02',
    'cto',
    ST_GeomFromText('POINT(-6.0571 37.3236)', 4326)
),
(
    'CTO-03',
    'cto',
    ST_GeomFromText('POINT(-6.0554 37.3251)', 4326)
),
(
    'ONT-01',
    'ont',
    ST_GeomFromText('POINT(-6.0542 37.3269)', 4326)
);
"""


def execute_sql_script(sql: str) -> None:
    with connection.cursor() as cur:
        cur.execute(sql)


@transaction.atomic
def bootstrap_vector_data(reset: bool = True) -> None:
    print(">> Creando tablas y geometrías demo...")
    execute_sql_script(VECTOR_SQL)

    if reset:
        print(">> Reseteando datos demo previos...")
        execute_sql_script(RESET_SQL)

    print(">> Insertando datos vectoriales demo...")
    execute_sql_script(SEED_SQL)


@transaction.atomic
def bootstrap_agent() -> Agent:
    print(">> Creando/actualizando agente demo...")

    agent, created = Agent.objects.update_or_create(
        name=AGENT_NAME,
        defaults={
            "system_prompt": AGENT_SYSTEM_PROMPT,
            "is_active": True,
            "profile": "rich",
            "tool_allowlist": [
                "utils.ping",
                "utils.now",
                "spatial.summary",
                "spatial.context_pack",
                "spatial.query_layer",
                "spatial.nearby",
                "spatial.intersects",
                "spatial.network_trace",
            ],
        },
    )

    if created:
        print(f"   - Agent creado: {agent.name} (id={agent.id})")
    else:
        print(f"   - Agent actualizado: {agent.name} (id={agent.id})")

    return agent


def print_settings_snippet() -> None:
    print("\nAñade esto en geoagents/settings.py si aún no lo tienes:\n")
    print(
        '''
AGENTS_GIS_LAYERS = [
    {
        "name": "demo_points",
        "table": "demo_points",
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["name", "category"],
        "filter_fields": ["name", "category"],
        "geometry_kind": "POINT",
    },
    {
        "name": "demo_lines",
        "table": "demo_lines",
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["name", "category"],
        "filter_fields": ["name", "category"],
        "geometry_kind": "LINESTRING",
    },
    {
        "name": "demo_polygons",
        "table": "demo_polygons",
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["name", "category"],
        "filter_fields": ["name", "category"],
        "geometry_kind": "POLYGON",
    },
]

AGENTS_MAX_PLANNER_TOOL_STEPS = 5
'''.strip()
    )
    print()


def print_test_payloads(agent: Agent) -> None:
    print("Payloads de prueba:\n")

    print("1) Resumen espacial general")
    print(
        {
            "agent": agent.id,
            "input_json": {
                "goal": "Analiza espacialmente esta zona y resume los elementos detectados",
                "map_context": {
                    "bbox": {
                        "west": -6.0605,
                        "south": 37.3205,
                        "east": -6.0530,
                        "north": 37.3275,
                    },
                    "zoom": 18,
                },
            },
        }
    )

    print("\n2) Trazado de red")
    print(
        {
            "agent": agent.id,
            "input_json": {
                "goal": "Traza una ruta por la red",
                "map_context": {
                    "bbox": {
                        "west": -6.0605,
                        "south": 37.3205,
                        "east": -6.0530,
                        "north": 37.3275,
                    },
                    "zoom": 18,
                },
                "trace_context": {
                    "start_point": {"lon": -6.0595, "lat": 37.3210},
                    "end_point": {"lon": -6.0540, "lat": 37.3270},
                },
            },
        }
    )

    print("\n3) Tool directa")
    print(
        {
            "agent": agent.id,
            "input_json": {
                "tool_call": {
                    "name": "spatial.query_layer",
                    "args": {
                        "layer": "demo_points",
                        "bbox": {
                            "west": -6.0605,
                            "south": 37.3205,
                            "east": -6.0530,
                            "north": 37.3275,
                        },
                        "limit": 20,
                    },
                }
            },
        }
    )


def main():
    print("=== BOOTSTRAP GEOAGENTS ===")
    bootstrap_vector_data(reset=True)
    agent = bootstrap_agent()
    print_settings_snippet()
    print_test_payloads(agent)
    print("\nBootstrap completado.")


if __name__ == "__main__":
    main()