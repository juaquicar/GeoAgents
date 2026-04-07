# Tests — GeoAgents

Todos los tests están centralizados en este directorio.  
Se ejecutan con el test runner de Django (`python manage.py test`).

---

## Requisitos previos
```bash
# BD local de test activa (Docker)
docker compose up -d


# Variables de entorno cargadas
# (el .env se carga automáticamente al arrancar Django)
```

---

## Ejecutar tests

### Suite completa

```bash
python manage.py test tests
```

### Módulo individual

```bash
python manage.py test tests.<nombre_archivo_sin_.py>
```

### Clase o método concreto

```bash
python manage.py test tests.test_api_core.AgentsCoreApiTests
python manage.py test tests.test_api_core.AgentsCoreApiTests.test_create_run_assigns_authenticated_user
```

---

## Descripción de los archivos

| Archivo | Qué cubre | BD real |
|---|---|---|
| `test_api_core.py` | API REST de agentes, runs, steps, trace, memoria, episodios, replan, ejecución paralela de steps, sesiones multi-turno | No (mocks) |
| `test_heuristics.py` | Clasificación de dominio, selección de tools, normalización de texto | No |
| `test_llm_synthesizer.py` | Extracción de hechos estructurados desde outputs de tools | No |
| `test_gis_inference.py` | Clasificación de geometría, inferencia de capas por goal | No |
| `test_gis_network_costing.py` | Motor de costes: grafo, multiplicadores, restricciones | No |
| `test_gis_network_api.py` | API de `spatial.network_service_area` (mocks de invoke_tool) | No (mocks) |
| `test_gis_network_integration.py` | Integración real de tools de red contra BD local de test | Sí (local) |
| `test_gis_aggregate.py` | Tool `spatial.aggregate`: unitarios (mocks) + integración local | Sí (local) |
| `test_gis_buffer.py` | Tool `spatial.buffer`: unitarios (mocks) + integración local | Sí (local) |
| `test_gis_alias.py` | Registro de aliases de BD en `agents_gis.service` | No |
| `test_gis_inspect.py` | Introspección GIS: unitarios (mocks) + integración BD remota | Opcional |

### Scripts de regresión manual (`manual/`)

No son `unittest` — se ejecutan directamente con Python contra la BD real.
No tienen aserciones automáticas: imprimen resultados para inspección visual.

| Script | Dominio GIS | BD necesaria |
|---|---|---|
| `manual/catastro.py` | Catastro español: parcelas, edificios, direcciones | BD remota catastro |
| `manual/planex.py` | Infraestructura telecom Planex: tramos (span), estructuras (struct) | BD remota Planex |

Cada script configura su agente con un `system_prompt` específico del dominio.
Ver la sección **Domain Configuration** en `CLAUDE.md` para ejemplos de `system_prompt` por dominio.

---

## Domain-agnostic design

GeoAgents funciona con cualquier dominio GIS: infraestructura, catastro, vegetación, activos urbanos, etc.

El `system_prompt` del agente es el **punto de configuración del dominio**. El planner LLM lo usa para:
- Interpretar la terminología del usuario y mapearla a capas reales del catálogo
- Decidir si existe red topológica (y si procede usar `spatial.network_trace`)
- Adaptar la síntesis al vocabulario del dominio

Las heurísticas (`agents_core/heuristics/`) son **agnósticas al dominio**: solo responden a keywords de operación espacial genérica (ruta, proximidad, intersección, agrupación…), no a nombres de capa ni términos específicos de un sector.

---

## Tests que requieren BD real

### BD local (test runner de Django)

`test_gis_network_integration.py` usa la BD de test que crea Django automáticamente.  
Requiere que **PostGIS esté instalado** en esa BD:

```bash
# Verificar que la extensión se puede crear (el test lo hace automáticamente)
python manage.py test tests.test_gis_network_integration
```

### BD remota (span + struct)

`test_gis_inspect.py` incluye tests de integración contra la BD remota real.  
**Se saltan automáticamente** si `GIS_REMOTE_DB_HOST` está vacío en el entorno.

Para ejecutarlos, asegúrate de que el `.env` tiene la BD remota configurada:

```env
GIS_REMOTE_DB_HOST=82.223.78.166
GIS_REMOTE_DB_PORT=5432
GIS_REMOTE_DB_NAME=tesa
GIS_REMOTE_DB_USER=postgres
GIS_REMOTE_DB_PASSWORD=
AGENTS_GIS_SCHEMA=planex
```

Luego:

```bash
# Solo tests de inspect (unitarios + integración si la BD está disponible)
python manage.py test tests.test_gis_inspect

# Solo unitarios (nunca necesitan BD)
python manage.py test tests.test_gis_inspect.InspectAgentGisUnitTests

# Solo integración real
python manage.py test tests.test_gis_inspect.InspectAgentGisRemoteIntegrationTests
```

Capas esperadas en la BD remota: **`span`** (line) y **`struct`** (point/polygon), schema `planex`.

---

## Arquitectura de conexiones en los tests

Cada `Agent` tiene sus propias conexiones GIS en el campo `gis_db_connections` (JSON).
Cuando está vacío (`[]`), `get_gis_connection()` usa el alias global `AGENTS_GIS_DB_ALIAS`
(configurable en `.env`; por defecto `"default"`).

### Patrones por tipo de test

- **Tests con mocks** (`test_gis_network_api.py`, `test_api_core.py`): agente sin
  `gis_db_connections` — las tools se interceptan con `@patch("agents_core.runner.invoke_tool")`.

- **Tests de integración local** (`test_gis_network_integration.py`): agente con
  `gis_db_connections=[]` y `gis_layers_catalog=[<tabla de test>]`.  
  El decorador `@override_settings(AGENTS_GIS_DB_ALIAS="default", AGENTS_GIS_SCHEMA="public")`
  fuerza el uso de la BD de test de Django, independientemente del `.env` de producción.  
  La clase también desconecta la señal `request_finished` y parchea `close_old_connections`
  en `agents_gis.service` para evitar que cierren la conexión envolvente de test.

- **Tests de integración remota** (`test_gis_inspect.py`): agente con
  `gis_db_connections=[{host, port, db_name, user, password, schema}]` apuntando a la BD remota.
  `inspect_agent_gis` abre una conexión psycopg2 directa sin pasar por Django.

### Consideración importante para tests de integración local

En el `.env` de producción puede estar `AGENTS_GIS_DB_ALIAS=gis_remote` y
`AGENTS_GIS_SCHEMA=planex`. Los tests de integración local **siempre** usan
`@override_settings` para forzar `default`/`public`, así no dependen del entorno.

---

---

## Scripts de regresión manual

Los scripts en `manual/` se ejecutan directamente con Python desde el root del proyecto
(necesitan que Django esté bootstrapeado y la BD remota accesible).

### `manual/catastro.py`

Prueba el agente catastro contra BD remota (parcelas, edificios, direcciones + red catastral).

```bash
# Todos los casos × 3 perfiles (28 casos × 3 = 84 runs)
python tests/manual/catastro.py

# Solo suite de red catastral
python tests/manual/catastro.py --suite network

# Solo consultas básicas
python tests/manual/catastro.py --suite catastro

# Filtrar por nombre de caso
python tests/manual/catastro.py --case summary

# Un solo perfil
python tests/manual/catastro.py --profile investigate

# Combinar filtros
python tests/manual/catastro.py --suite network --profile investigate --case route_cost
```

### `manual/planex.py`

Prueba el agente Planex contra BD remota (capas `span`/`struct` + red de canalización).

```bash
# Todos los casos × 3 perfiles (38 casos × 3 = 114 runs)
python tests/manual/planex.py

# Solo suite de red (span como grafo)
python tests/manual/planex.py --suite network

# Solo consultas básicas
python tests/manual/planex.py --suite basic

# Filtrar por nombre de caso
python tests/manual/planex.py --case service_area

# Un solo perfil
python tests/manual/planex.py --profile investigate
```

> **Nota:** estos scripts usan el alias global `AGENTS_GIS_DB_ALIAS` del `.env`.
> Los agentes se crean automáticamente en la BD si no existen.

---

## Ejecución rápida por área

```bash
# Solo core y API (sin BD GIS)
python manage.py test tests.test_api_core tests.test_heuristics tests.test_llm_synthesizer

# Solo GIS unitario (sin BD real)
python manage.py test tests.test_gis_inference tests.test_gis_network_costing tests.test_gis_network_api tests.test_gis_alias

# GIS con BD real (local + remota si está disponible)
python manage.py test tests.test_gis_network_integration tests.test_gis_inspect
```
