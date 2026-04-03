import json
import os
import sys
from pathlib import Path

import django

'''
Estructura del fichero                                                   
                                                                           
  Capas usadas
                                                                           
  ┌────────┬─────────────────┬──────────────────────────────────────────┐  
  │  Capa  │      Tipo       │                   Uso                    │
  ├────────┼─────────────────┼──────────────────────────────────────────┤  
  │ span   │ MULTILINESTRING │ Tramos de canalización (también como     │
  │        │                 │ grafo de red)                            │
  ├────────┼─────────────────┼──────────────────────────────────────────┤  
  │ struct │ MULTIPOINT      │ Estructuras de infraestructura           │
  │        │                 │ (arquetas, armarios...)                  │  
  └────────┴─────────────────┴──────────────────────────────────────────┘
                                                                           
  Suite basic — 20 casos sobre las herramientas estándar                   
              
  - summary (×3): resumen de inventario por zona (Sevilla, Madrid,         
  Barcelona)      
  - query (×5): consultas con filtros por category_n, type_name,           
  ducts_avai, te_tipo_ca, te_nro_lin                                       
  - nearby (×3): estructuras y tramos cercanos a un punto
  - intersects (×3): relación espacial entre span y struct                 
  - context_pack (×2): contexto completo de la zona                        
  - analíticos (×5): densidad, conductos disponibles, topología,           
  propietarios, longitudes                                                 
                                                                           
  Suite network — 18 casos sobre span como grafo de red                    
                    
  - network_trace (×4): 2 con LLM + 2 directos (Sevilla, Madrid)           
  - route_cost (×5): 2 con LLM + 3 directos (Sevilla, Madrid, Valencia) —
  métrica length                                                           
  - network_service_area (×5): 2 con LLM + 3 directos (300 m, 400 m, 350 m)
  - analíticos (×3): ruta óptima, cobertura, ruta + estructuras cercanas   
                                                                           
  Uso                                                                      
                                                                           
  python test_planex.py                          # todos los casos × 3 
  perfiles                                                                 
  python test_planex.py --suite basic            # solo consultas básicas
  python test_planex.py --suite network          # solo red sobre span     
  python test_planex.py --case summary           # filtro por nombre       
  python test_planex.py --profile investigate    # un solo perfil
                                                                           
  ▎ Nota: los bboxes usan las mismas zonas que test.py (Madrid, Sevilla,   
  Valencia, Barcelona). Si tu BD Planex cubre otra zona geográfica, ajusta 
  las coordenadas en la cabecera del fichero.  
'''

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
# BBoxes de zonas de infraestructura Planex (WGS84 lon/lat)
# Los datos están en SRID 25830; las tools reproyectan automáticamente.
# Ajusta las coordenadas a la zona real de tu BD si difieren.
# -----------------------------------------------------------------------------
BBOX_SEVILLA   = {"west": -5.998, "south": 37.383, "east": -5.985, "north": 37.393}
BBOX_MADRID    = {"west": -3.710, "south": 40.413, "east": -3.695, "north": 40.423}
BBOX_VALENCIA  = {"west": -0.382, "south": 39.467, "east": -0.370, "north": 39.477}
BBOX_BARCELONA = {"west":  2.155, "south": 41.378, "east":  2.170, "north": 41.388}

# Puntos de referencia para nearby (centro de cada bbox)
POINT_SEVILLA   = {"lon": -5.9915, "lat": 37.388}
POINT_MADRID    = {"lon": -3.7025, "lat": 40.418}
POINT_VALENCIA  = {"lon": -0.376,  "lat": 39.472}
POINT_BARCELONA = {"lon":  2.1625, "lat": 41.383}

# -----------------------------------------------------------------------------
# BBoxes reducidos para tests de red sobre span (~300-400 m × 300 m)
# -----------------------------------------------------------------------------
BBOX_NET_SEVILLA   = {"west": -5.996,  "south": 37.385, "east": -5.991,  "north": 37.388}
POINT_NET_SEV_SW   = {"lon": -5.996,   "lat": 37.385}
POINT_NET_SEV_NE   = {"lon": -5.991,   "lat": 37.388}
POINT_NET_SEV_MID  = {"lon": -5.9935,  "lat": 37.3865}

# Zona real de los datos Planex Madrid (structs fid 5732260 y 5732264 confirmados aquí)
BBOX_NET_MADRID    = {"west": -3.7143, "south": 40.4174, "east": -3.7125, "north": 40.4201}
POINT_NET_MAD_SW   = {"lon": -3.7143,  "lat": 40.4174}
POINT_NET_MAD_NE   = {"lon": -3.7125,  "lat": 40.4201}
POINT_NET_MAD_MID  = {"lon": -3.7134,  "lat": 40.4188}

BBOX_NET_VALENCIA  = {"west": -0.380,  "south": 39.469, "east": -0.373,  "north": 39.474}
POINT_NET_VAL_SW   = {"lon": -0.380,   "lat": 39.469}
POINT_NET_VAL_NE   = {"lon": -0.373,   "lat": 39.474}
POINT_NET_VAL_MID  = {"lon": -0.3765,  "lat": 39.4715}


# -----------------------------------------------------------------------------
# Casos de prueba PLANEX — capas básicas
# Capas disponibles: span (line), struct (point)
# Campos clave span: span_name, category_n, type_name, to_structu, from_struc,
#                    calculated, measured_l, ducts_avai, te_tipo_ca, te_num_cab, te_propiet
# Campos clave struct: structure_, category_n, type_name, location_c,
#                      te_tipo, te_nombre, te_zona, te_ciudad, te_capacid, te_nro_lin
# -----------------------------------------------------------------------------
PLANEX_TEST_CASES = [



    # --- SUMMARY: resumen de infraestructura por zona ---
    {
        "name": "summary_sevilla",
        "goal": (
            "Resume la infraestructura de canalización y estructuras disponible en esta zona: "
            "cuántos tramos (span) y estructuras (struct) hay"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "summary_madrid",
        "goal": (
            "Resume la infraestructura de red en esta zona: "
            "cuántos tramos de canalización y estructuras existen"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "summary_barcelona",
        "goal": (
            "Resume el inventario de infraestructura de esta zona: "
            "tramos (span) y estructuras (struct) disponibles"
        ),
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },

    # --- QUERY: explorar capas individuales ---
    {
        "name": "query_span_sevilla",
        "goal": (
            "Consulta los tramos de canalización (span) de esta zona "
            "y muestra su nombre, categoría, tipo y longitud medida"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "query_span_categoria_madrid",
        "goal": (
            "Lista los tramos de canalización de esta zona "
            "agrupados por categoría (category_n) y tipo (type_name)"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "query_struct_sevilla",
        "goal": (
            "Consulta las estructuras de infraestructura de esta zona "
            "y muestra su nombre, tipo, ciudad y capacidad"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "query_struct_madrid",
        "goal": (
            "Lista las estructuras de red en esta zona "
            "indicando su tipo (te_tipo), nombre (te_nombre) y número de líneas (te_nro_lin)"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "query_span_conductos_valencia",
        "goal": (
            "Obtén los tramos de canalización de esta zona "
            "e indica cuántos conductos disponibles (ducts_avai) tiene cada uno "
            "y el tipo de canalización (te_tipo_ca)"
        ),
        "map_context": {"bbox": BBOX_VALENCIA, "zoom": 17},
    },

    # --- NEARBY: elementos cercanos a un punto ---
    {
        "name": "nearby_struct_sevilla",
        "goal": (
            "¿Qué estructuras de infraestructura hay en un radio de 200 metros "
            "alrededor del centro del mapa? Muestra su tipo y nombre"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "nearby_span_madrid",
        "goal": (
            "¿Qué tramos de canalización (span) pasan a menos de 150 metros "
            "del centro de esta zona?"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "nearby_struct_barcelona",
        "goal": (
            "Busca las estructuras de red más cercanas al centro del mapa "
            "y muestra su categoría, tipo y propietario"
        ),
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },

    # --- INTERSECTS: relaciones espaciales entre capas ---
    {
        "name": "intersects_struct_span_sevilla",
        "goal": (
            "¿Qué estructuras intersectan o se solapan con tramos de canalización "
            "en esta zona? Relaciona struct con span"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "intersects_struct_span_madrid",
        "goal": (
            "¿Qué estructuras de red (struct) están dentro de los tramos de canalización (span) "
            "de esta zona? Encuentra la intersección espacial entre ambas capas"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "intersects_span_struct_valencia",
        "goal": (
            "Comprueba qué tramos de canalización (span) están asociados a "
            "qué estructuras (struct) en esta zona"
        ),
        "map_context": {"bbox": BBOX_VALENCIA, "zoom": 17},
    },

    # --- CONTEXT PACK: contexto completo de infraestructura ---
    {
        "name": "context_pack_sevilla",
        "goal": (
            "Construye un contexto completo de la infraestructura de red de esta zona: "
            "tramos de canalización, estructuras cercanas y sus relaciones espaciales"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "context_pack_madrid",
        "goal": (
            "Construye un contexto completo de la red de infraestructura de esta zona: "
            "tramos (span), estructuras (struct) y sus intersecciones"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },

    # --- ANALÍTICOS AVANZADOS (multi-herramienta) ---
    {
        "name": "analitico_inventario_sevilla",
        "goal": (
            "Analiza el inventario de infraestructura de esta zona: "
            "cuenta los tramos de canalización por categoría y tipo, "
            "e indica cuántas estructuras hay y de qué tipos predominan"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },
    {
        "name": "analitico_conductos_disponibles_madrid",
        "goal": (
            "Analiza la disponibilidad de conductos en la red de canalización de esta zona: "
            "¿qué tramos (span) tienen conductos disponibles (ducts_avai)? "
            "¿Cuántos conductos disponibles hay en total?"
        ),
        "map_context": {"bbox": BBOX_MADRID, "zoom": 17},
    },
    {
        "name": "analitico_topologia_barcelona",
        "goal": (
            "Analiza la distribución de la infraestructura en esta zona: "
            "¿cuántos tramos (span) hay y de qué categorías?, "
            "¿cuántas estructuras (struct) se registran y de qué tipos predominan?"
        ),
        "map_context": {"bbox": BBOX_BARCELONA, "zoom": 17},
    },
    {
        "name": "analitico_completo_valencia",
        "goal": (
            "Realiza un análisis completo de la infraestructura de red de esta zona: "
            "número de tramos y estructuras, propietarios (te_propiet/ownership_), "
            "tipos de canalización y qué estructuras están a menos de 100 metros del centro"
        ),
        "map_context": {"bbox": BBOX_VALENCIA, "zoom": 17},
    },
    {
        "name": "analitico_span_longitud_sevilla",
        "goal": (
            "Identifica los tramos de canalización más largos de esta zona "
            "según su longitud medida (measured_l o length) e indica su nombre y tipo"
        ),
        "map_context": {"bbox": BBOX_SEVILLA, "zoom": 17},
    },



]


# -----------------------------------------------------------------------------
# Casos de prueba RED PLANEX — herramientas de red sobre capa 'span'
# La capa span es MULTILINESTRING → se usa como grafo de red.
# network_trace, route_cost y network_service_area operan sobre sus segmentos.
# -----------------------------------------------------------------------------
PLANEX_NETWORK_TEST_CASES = [
    {
        "name": "network_trace_span_madrid_personalizada",
        "goal": (
            "Calcula la ruta por los tramos de canalización (span) entre dos estructuras (struct): "
            "primero consulta la capa struct para localizar los elementos con fid 5732260 y fid 5732261 "
            "y obtener sus coordenadas (sin restricción bbox), luego usa spatial.network_trace sobre span entre esos dos puntos"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },


    # --- NETWORK TRACE: camino mínimo por tramos de canalización ---
    {
        "name": "network_trace_span_sevilla",
        "goal": (
            "Traza el camino más corto por los tramos de canalización (span) "
            "entre el extremo suroeste y el noreste del área"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
    {
        "name": "network_trace_span_con_geom",
        "goal": (
            "Traza el camino por la red de canalización (span) entre los dos extremos del bbox "
            "e incluye la geometría de los tramos recorridos"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    # Llamada directa — network_trace sobre span Sevilla
    {
        "name": "network_trace_span_directo_sevilla",
        "goal": "Ruta directa por red span SW→NE en Sevilla",
        "tool_call": {
            "name": "spatial.network_trace",
            "args": {
                "layer": "span",
                "start_point": POINT_NET_SEV_SW,
                "end_point": POINT_NET_SEV_NE,
                "bbox": BBOX_NET_SEVILLA,
                "max_snap_distance_m": 100,
                "include_geom": False,
            },
        },
        "network": True,
    },
    # Llamada directa — network_trace sobre span Madrid
    {
        "name": "network_trace_span_directo_madrid",
        "goal": "Ruta directa por red span SW→NE en Madrid",
        "tool_call": {
            "name": "spatial.network_trace",
            "args": {
                "layer": "span",
                "start_point": POINT_NET_MAD_SW,
                "end_point": POINT_NET_MAD_NE,
                "bbox": BBOX_NET_MADRID,
                "max_snap_distance_m": 100,
                "include_geom": False,
            },
        },
        "network": True,
    },

    # --- ROUTE COST: ruta con coste sobre red de canalización ---
    {
        "name": "route_cost_span_por_longitud_sevilla",
        "goal": (
            "Calcula la ruta óptima por longitud usando los tramos de canalización (span) "
            "entre el extremo suroeste y el noreste del área"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
    {
        "name": "route_cost_span_por_longitud_madrid",
        "goal": (
            "Calcula la ruta más corta en metros por los tramos de canalización (span) "
            "entre los dos extremos de esta zona"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    # Llamada directa — route_cost sobre span Sevilla
    {
        "name": "route_cost_span_directo_sevilla",
        "goal": "Ruta con coste directa por span SW→NE en Sevilla",
        "tool_call": {
            "name": "spatial.route_cost",
            "args": {
                "layer": "span",
                "start_point": POINT_NET_SEV_SW,
                "end_point": POINT_NET_SEV_NE,
                "bbox": BBOX_NET_SEVILLA,
                "metric": "length",
                "include_geom": False,
                "max_snap_distance_m": 100,
            },
        },
        "network": True,
    },
    # Llamada directa — route_cost sobre span Madrid
    {
        "name": "route_cost_span_directo_madrid",
        "goal": "Ruta con coste directa por span SW→NE en Madrid",
        "tool_call": {
            "name": "spatial.route_cost",
            "args": {
                "layer": "span",
                "start_point": POINT_NET_MAD_SW,
                "end_point": POINT_NET_MAD_NE,
                "bbox": BBOX_NET_MADRID,
                "metric": "length",
                "include_geom": False,
                "max_snap_distance_m": 100,
            },
        },
        "network": True,
    },
    # Llamada directa — route_cost sobre span Valencia
    {
        "name": "route_cost_span_directo_valencia",
        "goal": "Ruta con coste directa por span SW→NE en Valencia",
        "tool_call": {
            "name": "spatial.route_cost",
            "args": {
                "layer": "span",
                "start_point": POINT_NET_VAL_SW,
                "end_point": POINT_NET_VAL_NE,
                "bbox": BBOX_NET_VALENCIA,
                "metric": "length",
                "include_geom": False,
                "max_snap_distance_m": 100,
            },
        },
        "network": True,
    },

    # --- SERVICE AREA: alcance desde una estructura sobre red de span ---
    {
        "name": "service_area_span_sevilla",
        "goal": (
            "¿A qué tramos de canalización se puede llegar recorriendo 300 metros "
            "por la red de span desde el punto central del mapa?"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
    {
        "name": "service_area_span_madrid",
        "goal": (
            "Calcula el área de servicio alcanzable desde el punto central "
            "con un máximo de 400 metros por la red de canalización (span)"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    # Llamada directa — service_area sobre span Sevilla
    {
        "name": "service_area_span_directo_sevilla",
        "goal": "Área de servicio 300 m desde centro Sevilla por span",
        "tool_call": {
            "name": "spatial.network_service_area",
            "args": {
                "layer": "span",
                "origin_point": POINT_NET_SEV_MID,
                "bbox": BBOX_NET_SEVILLA,
                "max_distance_m": 300.0,
                "include_geom": False,
                "max_snap_distance_m": 100,
            },
        },
        "network": True,
    },
    # Llamada directa — service_area sobre span Madrid
    {
        "name": "service_area_span_directo_madrid",
        "goal": "Área de servicio 400 m desde centro Madrid por span",
        "tool_call": {
            "name": "spatial.network_service_area",
            "args": {
                "layer": "span",
                "origin_point": POINT_NET_MAD_MID,
                "bbox": BBOX_NET_MADRID,
                "max_distance_m": 400.0,
                "include_geom": False,
                "max_snap_distance_m": 100,
            },
        },
        "network": True,
    },
    # Llamada directa — service_area sobre span Valencia
    {
        "name": "service_area_span_directo_valencia",
        "goal": "Área de servicio 350 m desde centro Valencia por span",
        "tool_call": {
            "name": "spatial.network_service_area",
            "args": {
                "layer": "span",
                "origin_point": POINT_NET_VAL_MID,
                "bbox": BBOX_NET_VALENCIA,
                "max_distance_m": 350.0,
                "include_geom": False,
                "max_snap_distance_m": 100,
            },
        },
        "network": True,
    },

    # --- ANALÍTICOS multi-herramienta de red Planex ---
    {
        "name": "analitico_red_ruta_optima_sevilla",
        "goal": (
            "Calcula la ruta más corta entre los dos extremos del bbox "
            "usando la red de canalización (span) e indica la longitud total del camino "
            "y cuántos tramos lo componen"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
    {
        "name": "analitico_red_cobertura_madrid",
        "goal": (
            "Desde el punto central del mapa, ¿qué tramos de canalización (span) "
            "son alcanzables en menos de 350 metros por la red? "
            "Resume cuántos segmentos y qué longitud total cubre el área de servicio"
        ),
        "map_context": {"bbox": BBOX_NET_MADRID, "zoom": 18},
        "network": True,
    },
    {
        "name": "analitico_red_y_estructuras_sevilla",
        "goal": (
            "Analiza la red de canalización de esta zona: "
            "calcula la ruta más corta entre los extremos del bbox por los tramos (span) "
            "y enumera las estructuras (struct) más cercanas al origen de la ruta"
        ),
        "map_context": {"bbox": BBOX_NET_SEVILLA, "zoom": 18},
        "network": True,
    },
]


# Catálogo completo
TEST_CASES = PLANEX_TEST_CASES + PLANEX_NETWORK_TEST_CASES

PROFILES = ["compact", "rich", "investigate"]

PLANEX_TOOL_ALLOWLIST = [
    "utils.ping",
    "utils.now",
    "spatial.summary",
    "spatial.query_layer",
    "spatial.nearby",
    "spatial.intersects",
    "spatial.context_pack",
]

PLANEX_NETWORK_TOOL_ALLOWLIST = [
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
        username="test_planex",
        defaults={"email": "test_planex@example.com"},
    )
    return user


def get_or_create_agent(profile: str, *, network: bool = False) -> Agent:
    allowlist = PLANEX_NETWORK_TOOL_ALLOWLIST if network else PLANEX_TOOL_ALLOWLIST
    agent_name = f"test-planex-network-{profile}" if network else f"test-planex-{profile}"
    system_prompt = (
        "Eres un agente especializado en análisis de redes de canalización e infraestructura Planex."
        if network
        else "Eres un agente especializado en análisis de infraestructura de canalización y red Planex."
    )

    agent, _ = Agent.objects.get_or_create(
        name=agent_name,
        defaults={
            "system_prompt": system_prompt,
            "is_active": True,
            "tool_allowlist": allowlist,
            "profile": profile,
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
    suite_tag = "[RED]" if result.get("network") else "[PLANEX]"
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
    ko = [r for r in results if r["status"] != "succeeded"]

    print("=" * 110)
    print(f"RESUMEN  — total={len(results)}  ok={len(ok)}  ko={len(ko)}")
    print("=" * 110)
    for r in results:
        icon = "✔" if r["status"] == "succeeded" else "✘"
        suite_tag = "[RED]" if r.get("network") else "[PLX]"
        print(
            f"  {icon} {suite_tag} [{r['profile']:<10}] {r['case_name']:<55} "
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
        suite_tag = "[RED]" if rows[0].get("network") else "[PLX]"
        print(f"\nCASE: {case_name}  {suite_tag}")
        for row in sorted(rows, key=lambda x: x["profile"]):
            direct_info = (
                f"  ok={row.get('tool_result', {}).get('ok')}"
                if row.get("direct")
                else f"  len={len(row['final_text'])}"
            )
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
        python test_planex.py                          # todos los casos, todos los perfiles
        python test_planex.py --suite network          # solo casos de red (span como grafo)
        python test_planex.py --suite basic            # solo casos básicos (query, nearby, etc.)
        python test_planex.py --case summary           # filtro substring en nombre
        python test_planex.py --profile investigate    # solo ese perfil
    """
    import argparse
    parser = argparse.ArgumentParser(description="Batería de pruebas GeoAgents — Planex")
    parser.add_argument("--case", default=None, help="Filtro (substring) en el nombre del caso")
    parser.add_argument("--profile", default=None, choices=PROFILES + ["all"], help="Perfil a ejecutar")
    parser.add_argument(
        "--suite",
        default="all",
        choices=["all", "basic", "network"],
        help="Suite de pruebas: all (defecto), basic, network",
    )
    parser.add_argument("positional", nargs="*")
    return parser.parse_args()


def main():
    args = parse_args()

    case_filter = args.case
    profile_filter = args.profile
    suite_filter = args.suite

    if args.positional:
        if len(args.positional) >= 1 and not case_filter:
            case_filter = args.positional[0]
        if len(args.positional) >= 2 and not profile_filter:
            profile_filter = args.positional[1]

    if suite_filter == "basic":
        cases = list(PLANEX_TEST_CASES)
    elif suite_filter == "network":
        cases = list(PLANEX_NETWORK_TEST_CASES)
    else:
        cases = list(TEST_CASES)

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
