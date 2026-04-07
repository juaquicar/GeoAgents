import json
import os
import sys
from pathlib import Path

import django

# -----------------------------------------------------------------------------
# Bootstrap Django
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoagents.settings")
django.setup()

from django.contrib.auth import get_user_model   # noqa: E402
from agents_core.models import Agent, Run        # noqa: E402
from agents_core.runner import execute_run       # noqa: E402


# -----------------------------------------------------------------------------
# Conexión y catálogo hardcodeados (modelo per-agent)
# TODO: rellena los datos de acceso a la BD del catastro español.
# -----------------------------------------------------------------------------
GIS_DB_CONNECTION = {
    "host": "",          # ej. "82.223.78.166"
    "port": 5432,
    "db_name": "",       # ej. "catastro"
    "user": "",          # ej. "postgres"
    "password": "",
    "schema": "public",  # ajusta si el schema no es public
    "alias": "catastro",
}

CATASTRO_CATALOG = [
    {
        "name": "addresses",
        "table": "addresses",
        "schema": GIS_DB_CONNECTION["schema"],
        "geom_col": "the_geom",
        "id_col": "gid",
        "geometry_kind": "point",
        "srid": 4326,
        "fields": ["designator", "locator_designator", "thoroughfare_name", "postal_code", "admin_unit"],
        "filter_fields": ["designator", "locator_designator", "thoroughfare_name", "postal_code"],
    },
    {
        "name": "buildings",
        "table": "buildings",
        "schema": GIS_DB_CONNECTION["schema"],
        "geom_col": "the_geom",
        "id_col": "gid",
        "geometry_kind": "polygon",
        "srid": 4326,
        "fields": ["localid", "currentuse", "numberoffloors", "numberofbuildingunit", "conditionofconstruction", "beginning"],
        "filter_fields": ["localid", "currentuse", "numberoffloors", "numberofbuildingunit", "conditionofconstruction"],
    },
    {
        "name": "cadastralparcels",
        "table": "cadastralparcels",
        "schema": GIS_DB_CONNECTION["schema"],
        "geom_col": "the_geom",
        "id_col": "gid",
        "geometry_kind": "polygon",
        "srid": 4326,
        "fields": ["nationalcadastralreference", "areavalue", "label"],
        "filter_fields": ["nationalcadastralreference", "areavalue", "label"],
    },
]


# -----------------------------------------------------------------------------
# BBoxes reales del catastro español
# -----------------------------------------------------------------------------
BBOX_MADRID = {"west": -3.710, "south": 40.413, "east": -3.695, "north": 40.423}
BBOX_SEVILLA = {"west": -5.998, "south": 37.383, "east": -5.985, "north": 37.393}
BBOX_VALENCIA = {"west": -0.382, "south": 39.467, "east": -0.370, "north": 39.477}
BBOX_BARCELONA = {"west": 2.155, "south": 41.378, "east": 2.170, "north": 41.388}

# Puntos de referencia para nearby (centro de cada bbox)
POINT_MADRID = {"lon": -3.7025, "lat": 40.418}
POINT_SEVILLA = {"lon": -5.9915, "lat": 37.388}
POINT_VALENCIA = {"lon": -0.376, "lat": 39.472}
POINT_BARCELONA = {"lon": 2.1625, "lat": 41.383}

# -----------------------------------------------------------------------------
# Zonas reducidas para tests de red sobre aristas de cadastralparcels
# (~300 m × 300 m para limitar el número de polígonos extraídos)
# -----------------------------------------------------------------------------
# Madrid: zona centro ~350 m × 330 m
BBOX_NET_MADRID = {"west": -3.7055, "south": 40.4165, "east": -3.7020, "north": 40.4192}
POINT_NET_MADRID_SW  = {"lon": -3.7055, "lat": 40.4165}
POINT_NET_MADRID_NE  = {"lon": -3.7020, "lat": 40.4192}
POINT_NET_MADRID_MID = {"lon": -3.7037, "lat": 40.4178}

# Sevilla: zona centro ~420 m × 330 m
BBOX_NET_SEVILLA = {"west": -5.996, "south": 37.385, "east": -5.991, "north": 37.388}
POINT_NET_SEVILLA_SW  = {"lon": -5.996,  "lat": 37.385}
POINT_NET_SEVILLA_NE  = {"lon": -5.991,  "lat": 37.388}
POINT_NET_SEVILLA_MID = {"lon": -5.9935, "lat": 37.3865}


# -----------------------------------------------------------------------------
# Casos de prueba CATASTRO
# Capas disponibles: addresses (point), buildings (polygon), cadastralparcels (polygon)
# -----------------------------------------------------------------------------
CATASTRO_TEST_CASES = [

    # --- SUMMARY: resumen catastral por zonas ---
    {
        "name": "summary_madrid",
        "goal": "Resume el contenido catastral de esta zona: cuántas parcelas, edificios y direcciones hay",
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "summary_sevilla",
        "goal": "Resume el contenido catastral de esta zona: cuántas parcelas, edificios y direcciones hay",
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "summary_barcelona",
        "goal": "Resume el contenido catastral de esta zona: cuántas parcelas, edificios y direcciones hay",
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },

    # --- QUERY: explorar capas individuales ---
    {
        "name": "query_parcelas_madrid",
        "goal": "Consulta las parcelas catastrales de esta zona y muestra su referencia catastral y área",
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "query_edificios_sevilla",
        "goal": "Lista los edificios de esta zona con su uso actual, número de viviendas y año de construcción",
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "query_direcciones_valencia",
        "goal": "Obtén las direcciones postales de esta zona con su designador y código catastral",
        "map_context": {"bbox": BBOX_VALENCIA, "zoom": 17},
    },

    # --- NEARBY: elementos cercanos a un punto ---
    {
        "name": "nearby_direcciones_madrid",
        "goal": "¿Qué direcciones postales hay en un radio de 150 metros alrededor del centro del mapa?",
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "nearby_edificios_barcelona",
        "goal": "¿Qué edificios hay más cercanos al centro del mapa? Muestra cuántas viviendas tiene cada uno",
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },
    {
        "name": "nearby_parcelas_sevilla",
        "goal": "Busca las parcelas catastrales más cercanas al centro de esta zona",
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },

    # --- INTERSECTS: relaciones espaciales entre capas ---
    {
        "name": "intersects_edificios_parcelas_madrid",
        "goal": "¿Qué edificios intersectan con qué parcelas catastrales en esta zona?",
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "intersects_direcciones_parcelas_valencia",
        "goal": "Relaciona las direcciones postales con las parcelas catastrales en las que se encuentran",
        "map_context": {"bbox": BBOX_VALENCIA, "zoom": 17},
    },
    {
        "name": "intersects_direcciones_edificios_barcelona",
        "goal": "Comprueba qué direcciones postales están dentro de qué edificios en esta zona",
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },

    # --- CONTEXT PACK: contexto catastral completo ---
    {
        "name": "context_pack_madrid",
        "goal": "Construye un contexto catastral completo de esta zona: parcelas, edificios y direcciones cercanas",
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "context_pack_sevilla",
        "goal": "Construye un contexto catastral completo de esta zona: parcelas, edificios y direcciones cercanas",
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },

    # --- ANALÍTICOS AVANZADOS (multi-herramienta) ---
    {
        "name": "analitico_densidad_madrid",
        "goal": (
            "Analiza la densidad edificatoria de esta zona: "
            "cuenta los edificios, calcula cuántas viviendas hay en total "
            "y resume el estado de construcción predominante"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "analitico_uso_sevilla",
        "goal": (
            "Analiza los usos del suelo en esta zona según el catastro: "
            "¿predomina el uso residencial, comercial u otro? "
            "¿Cuántas parcelas y edificios hay?"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "analitico_parcela_ref_barcelona",
        "goal": (
            "Busca la parcela catastral con mayor área en esta zona "
            "e indica su referencia catastral nacional"
        ),
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },
    {
        "name": "analitico_completo_valencia",
        "goal": (
            "Realiza un análisis catastral completo de esta zona: "
            "cuántas parcelas, edificios y direcciones hay, "
            "qué edificios tienen más de 5 viviendas "
            "y qué relación espacial existe entre direcciones y parcelas"
        ),
        "map_context": {"bbox": BBOX_VALENCIA, "zoom": 17},
    },
]

# -----------------------------------------------------------------------------
# Casos de prueba RED (cadastralparcels, BD remota catastro)
# Las herramientas extraen automáticamente las aristas de los límites de parcelas
# como tramos de red. No se necesita parchear settings — se usa la BD gis_remote.
# network=True solo identifica la suite; no implica cambio de settings.
# -----------------------------------------------------------------------------
NETWORK_TEST_CASES = [

    # --- NETWORK TRACE: camino mínimo por aristas de parcelas ---
    {
        "name": "network_trace_basico",
        "goal": (
            "Traza el camino más corto por las aristas de las parcelas catastrales "
            "entre el extremo suroeste y el noreste del bbox"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    {
        "name": "network_trace_con_geom",
        "goal": (
            "Traza el camino por la red catastral entre los dos extremos del bbox "
            "e incluye la geometría de los tramos recorridos"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    # Llamada directa — network_trace sobre cadastralparcels
    {
        "name": "network_trace_directo",
        "goal": "Ruta directa por red catastral SW→NE en Madrid",
        "tool_call": {
            "name": "spatial.network_trace",
            "args": {
                "layer": "cadastralparcels",
                "start_point": POINT_NET_MADRID_SW,
                "end_point": POINT_NET_MADRID_NE,
                "bbox": BBOX_NET_MADRID,
                "max_snap_distance_m": 50,
                "include_geom": False,
            },
        },
        "network": True,
    },

    # --- ROUTE COST: ruta con coste sobre red catastral ---
    {
        "name": "route_cost_por_distancia",
        "goal": (
            "Calcula la ruta óptima por longitud usando las aristas de las parcelas catastrales "
            "entre el extremo suroeste y el noreste del área"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    # Llamada directa — route_cost sobre cadastralparcels Madrid
    {
        "name": "route_cost_directo_madrid",
        "goal": "Ruta con coste directa por parcelas SW→NE en Madrid",
        "tool_call": {
            "name": "spatial.route_cost",
            "args": {
                "layer": "cadastralparcels",
                "start_point": POINT_NET_MADRID_SW,
                "end_point": POINT_NET_MADRID_NE,
                "bbox": BBOX_NET_MADRID,
                "metric": "length",
                "include_geom": False,
                "max_snap_distance_m": 50,
            },
        },
        "network": True,
    },
    # Llamada directa — route_cost sobre cadastralparcels Sevilla
    {
        "name": "route_cost_directo_sevilla",
        "goal": "Ruta con coste directa por parcelas SW→NE en Sevilla",
        "tool_call": {
            "name": "spatial.route_cost",
            "args": {
                "layer": "cadastralparcels",
                "start_point": POINT_NET_SEVILLA_SW,
                "end_point": POINT_NET_SEVILLA_NE,
                "bbox": BBOX_NET_SEVILLA,
                "metric": "length",
                "include_geom": False,
                "max_snap_distance_m": 50,
            },
        },
        "network": True,
    },

    # --- SERVICE AREA: alcance desde un punto sobre red catastral ---
    {
        "name": "service_area_por_distancia",
        "goal": (
            "¿A qué parcelas se puede llegar caminando 200 metros por las aristas de las parcelas "
            "desde el punto central del mapa?"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    {
        "name": "service_area_por_coste",
        "goal": (
            "Calcula el área de servicio alcanzable desde el punto central "
            "con un coste máximo de 300 metros en la red catastral"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
    # Llamada directa — service_area por distancia desde Madrid
    {
        "name": "service_area_distancia_directa",
        "goal": "Área de servicio 200 m desde centro Madrid por parcelas",
        "tool_call": {
            "name": "spatial.network_service_area",
            "args": {
                "layer": "cadastralparcels",
                "origin_point": POINT_NET_MADRID_MID,
                "bbox": BBOX_NET_MADRID,
                "max_distance_m": 200.0,
                "include_geom": False,
                "max_snap_distance_m": 50,
            },
        },
        "network": True,
    },
    # Llamada directa — service_area por distancia desde Sevilla
    {
        "name": "service_area_distancia_sevilla",
        "goal": "Área de servicio 250 m desde centro Sevilla por parcelas",
        "tool_call": {
            "name": "spatial.network_service_area",
            "args": {
                "layer": "cadastralparcels",
                "origin_point": POINT_NET_SEVILLA_MID,
                "bbox": BBOX_NET_SEVILLA,
                "max_distance_m": 250.0,
                "include_geom": False,
                "max_snap_distance_m": 50,
            },
        },
        "network": True,
    },

    # --- ANALÍTICOS multi-herramienta de red catastral ---
    {
        "name": "analitico_red_ruta_optima",
        "goal": (
            "Calcula la ruta más corta entre los dos extremos del bbox usando las aristas "
            "de las parcelas catastrales como red, e indica la longitud total del camino"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    {
        "name": "analitico_red_cobertura",
        "goal": (
            "Desde el punto central del mapa, ¿qué parcelas catastrales son alcanzables "
            "en menos de 200 metros por sus aristas? Resume cuántos nodos se alcanzan"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
]

# Catálogo completo
TEST_CASES = CATASTRO_TEST_CASES + NETWORK_TEST_CASES

PROFILES = ["compact", "rich", "investigate"]

CATASTRO_TOOL_ALLOWLIST = [
    "utils.ping",
    "utils.now",
    "spatial.summary",
    "spatial.query_layer",
    "spatial.nearby",
    "spatial.intersects",
    "spatial.context_pack",
]

NETWORK_TOOL_ALLOWLIST = [
    "utils.ping",
    "utils.now",
    "spatial.summary",
    "spatial.query_layer",
    "spatial.nearby",
    "spatial.intersects",
    "spatial.context_pack",
    "spatial.network_trace",
    "spatial.route_cost",
    "spatial.network_service_area",
]


# -----------------------------------------------------------------------------
# Infraestructura de ejecución
# -----------------------------------------------------------------------------

def get_or_create_user():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_catastro",
        defaults={"email": "test_catastro@example.com"},
    )
    return user


def get_or_create_agent(profile: str, *, network: bool = False) -> Agent:
    allowlist = NETWORK_TOOL_ALLOWLIST if network else CATASTRO_TOOL_ALLOWLIST
    agent_name = f"test-network-{profile}" if network else f"test-catastro-{profile}"
    system_prompt = (
        "Eres un agente especializado en análisis de redes de infraestructura."
        if network
        else "Eres un agente especializado en análisis catastral español."
    )

    agent, _ = Agent.objects.get_or_create(
        name=agent_name,
        defaults={
            "system_prompt": system_prompt,
            "is_active": True,
            "tool_allowlist": allowlist,
            "profile": profile,
            "gis_db_connections": [GIS_DB_CONNECTION],
            "gis_layers_catalog": CATASTRO_CATALOG,
        },
    )

    changed = False
    if agent.profile != profile:
        agent.profile = profile
        changed = True
    if agent.tool_allowlist != allowlist:
        agent.tool_allowlist = allowlist
        changed = True
    if not agent.is_active:
        agent.is_active = True
        changed = True
    if agent.gis_db_connections != [GIS_DB_CONNECTION]:
        agent.gis_db_connections = [GIS_DB_CONNECTION]
        changed = True
    if agent.gis_layers_catalog != CATASTRO_CATALOG:
        agent.gis_layers_catalog = CATASTRO_CATALOG
        changed = True
    if changed:
        agent.save()

    return agent


def extract_tool_names(steps: list) -> list[str]:
    return [s.get("name") for s in steps if s.get("type") == "tool"]


def run_case(profile: str, case: dict) -> dict:
    is_network = bool(case.get("network"))
    user = get_or_create_user()
    agent = get_or_create_agent(profile, network=is_network)

    input_json: dict = {"goal": case["goal"]}
    if "map_context" in case:
        input_json["map_context"] = case["map_context"]
    if "tool_call" in case:
        input_json["tool_call"] = case["tool_call"]

    run = Run.objects.create(
        agent=agent,
        user=user,
        input_json=input_json,
        status="queued",
    )

    run = execute_run(run)
    run.refresh_from_db()

    output = run.output_json or {}

    # Resultado directo (tool_call path): output tiene "tool", no "plan"
    if "tool" in output and "plan" not in output:
        return {
            "case_name": case["name"],
            "goal": case["goal"],
            "profile": profile,
            "run_id": run.id,
            "status": run.status,
            "error": run.error,
            "steps": [],
            "tool_names": [output.get("tool")],
            "tool_result": {
                "ok": output.get("ok"),
                "error": output.get("error"),
                "data_keys": list((output.get("data") or {}).keys()),
            },
            "final_text": "",
            "network": is_network,
            "direct": True,
        }

    plan = output.get("plan", {}) or {}
    meta = plan.get("_meta", {}) or {}

    return {
        "case_name": case["name"],
        "goal": case["goal"],
        "profile": profile,
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "steps": plan.get("steps", []),
        "tool_names": extract_tool_names(plan.get("steps", [])),
        "raw_plan": meta.get("raw_plan", {}),
        "validated_plan": meta.get("validated_plan", {}),
        "normalized_plan": meta.get("normalized_plan", {}),
        "final_text": run.final_text or output.get("final_text", ""),
        "network": is_network,
        "direct": False,
    }


def print_case_result(result: dict) -> None:
    suite_tag = "[RED]" if result.get("network") else "[CATASTRO]"
    direct_tag = " [DIRECTO]" if result.get("direct") else ""
    print("=" * 110)
    print(f"CASE    : {result['case_name']}  {suite_tag}{direct_tag}")
    print(f"PROFILE : {result['profile']}")
    print(f"RUN ID  : {result['run_id']}")
    print(f"STATUS  : {result['status']}")
    print(f"ERROR   : {result['error']}")
    print(f"GOAL    : {result['goal']}")
    print("-" * 110)
    print("TOOLS   :", result["tool_names"])
    print("-" * 110)
    if result.get("direct"):
        tr = result.get("tool_result") or {}
        print(f"TOOL RESULT: ok={tr.get('ok')}  error={tr.get('error')}  data_keys={tr.get('data_keys')}")
    else:
        print("STEPS:")
        print(json.dumps(result["steps"], ensure_ascii=False, indent=2))
        print("-" * 110)
        print("FINAL TEXT:")
        print(result["final_text"])
    print()


def summarize_results(results: list[dict]) -> None:
    ok = [r for r in results if r["status"] == "succeeded"]
    ko = [r for r in results if r["status"] != "done"]

    print("=" * 110)
    print(f"RESUMEN  — total={len(results)}  ok={len(ok)}  ko={len(ko)}")
    print("=" * 110)
    for r in results:
        icon = "✔" if r["status"] == "succeeded" else "✘"
        suite_tag = "[RED]" if r.get("network") else "[CAT]"
        print(
            f"  {icon} {suite_tag} [{r['profile']:<10}] {r['case_name']:<45} "
            f"status={r['status']:<8} tools={r['tool_names']}"
        )
        if r["error"]:
            print(f"    ERROR: {r['error']}")


def print_case_matrix(results: list[dict]) -> None:
    print()
    print("=" * 110)
    print("MATRIZ POR CASO")
    print("=" * 110)

    grouped = {}
    for r in results:
        grouped.setdefault(r["case_name"], []).append(r)

    for case_name, rows in grouped.items():
        suite_tag = "[RED]" if rows[0].get("network") else "[CAT]"
        print(f"\nCASE: {case_name}  {suite_tag}")
        for row in sorted(rows, key=lambda x: x["profile"]):
            direct_info = f"  ok={row.get('tool_result', {}).get('ok')}" if row.get("direct") else f"  len={len(row['final_text'])}"
            print(
                f"  - {row['profile']:<12} status={row['status']:<10} "
                f"tools={row['tool_names']}{direct_info}"
            )


# -----------------------------------------------------------------------------
# Selección de casos / perfiles / suite por argumento de línea de comandos
# -----------------------------------------------------------------------------

def parse_args():
    """
    Uso:
        python test.py                              # todos los casos, todos los perfiles
        python test.py --suite network              # solo casos de red
        python test.py --suite catastro             # solo casos catastrales
        python test.py --case network_trace         # filtro substring en nombre
        python test.py --profile investigate        # solo ese perfil
        python test.py network_trace investigate    # posicional legacy
    """
    import argparse
    parser = argparse.ArgumentParser(description="Batería de pruebas GeoAgents")
    parser.add_argument("--case", default=None, help="Filtro (substring) en el nombre del caso")
    parser.add_argument("--profile", default=None, choices=PROFILES + ["all"], help="Perfil a ejecutar")
    parser.add_argument(
        "--suite",
        default="all",
        choices=["all", "catastro", "network"],
        help="Suite de pruebas: all (defecto), catastro, network",
    )
    # Compat con invocación posicional legacy
    parser.add_argument("positional", nargs="*")
    return parser.parse_args()


def main():
    args = parse_args()

    # Filtros
    case_filter = args.case
    profile_filter = args.profile
    suite_filter = args.suite

    if args.positional:
        if len(args.positional) >= 1 and not case_filter:
            case_filter = args.positional[0]
        if len(args.positional) >= 2 and not profile_filter:
            profile_filter = args.positional[1]

    # Selección de suite
    if suite_filter == "catastro":
        cases = list(CATASTRO_TEST_CASES)
    elif suite_filter == "network":
        cases = list(NETWORK_TEST_CASES)
    else:
        cases = list(TEST_CASES)

    # Filtro por nombre
    if case_filter:
        cases = [c for c in cases if case_filter in c["name"]]
        if not cases:
            print(f"[WARN] Ningún caso coincide con el filtro '{case_filter}'")
            return

    profiles = PROFILES
    if profile_filter and profile_filter != "all":
        profiles = [profile_filter]

    print(f"Ejecutando {len(cases)} caso(s) × {len(profiles)} perfil(es) "
          f"= {len(cases) * len(profiles)} run(s)\n")

    results = []
    for case in cases:
        for profile in profiles:
            result = run_case(profile, case)
            results.append(result)
            print_case_result(result)

    summarize_results(results)
    print_case_matrix(results)


if __name__ == "__main__":
    main()
