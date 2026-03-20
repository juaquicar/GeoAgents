# GeoAgents Usage Guide

Esta guía explica cómo:

* crear agentes
* crear y ejecutar runs
* interpretar resultados
* usar `trace` y `steps`
* ejecutar tools directamente
* extender el framework

---

# Crear un agente

Ejemplo en Django shell:

```bash
python manage.py shell
```

```python id="7tdehe"
from agents_core.models import Agent

agent = Agent.objects.create(
    name="geo-agent",
    system_prompt="Eres un experto en análisis espacial.",
    profile="rich",
    tool_allowlist=[
        "spatial.intersects",
        "spatial.nearby",
        "spatial.query_layer",
        "spatial.context_pack",
        "spatial.network_trace",
    ],
)
```

---

# Crear un run

Ejemplo:

```python id="kyhedk"
from agents_core.models import Run

run = Run.objects.create(
    agent=agent,
    user=user,
    input_json={
        "goal": "Comprueba si existe una ruta de red válida entre dos puntos",
        "map_context": {
            "bbox": {
                "west": -6.06,
                "south": 37.32,
                "east": -6.05,
                "north": 37.33
            },
            "zoom": 18
        }
    }
)
```

Estado esperado justo después de crear:

```python id="vti8dj"
run.status
# "queued"
```

---

# Ejecutar un run

```python id="c2xb2n"
from agents_core.runner import execute_run

run = execute_run(run)
```

Esto dispara el ciclo completo:

```text id="q994tc"
plan -> execute -> verify -> optional replan -> synthesize
```

---

# Leer el resultado

## Respuesta final

```python id="rvgr5p"
run.final_text
```

Contiene la síntesis en lenguaje natural.

## Payload técnico completo

```python id="rwjw4a"
run.output_json
```

Contiene el resultado estructurado del run.

Campos típicos:

* `ok`
* `goal`
* `plan`
* `plan_history`
* `replan_count`
* `executed_outputs`
* `final_text`

---

# Inspeccionar outputs ejecutados

Puedes revisar cada step tool ejecutado en:

```python id="8s2x0x"
run.output_json["executed_outputs"]
```

Ejemplo de contenido:

```json id="z0ercf"
[
  {
    "id": "s1",
    "type": "tool",
    "name": "spatial.network_trace",
    "ok": true,
    "resolved_args": {
      "layer": "demo_lines",
      "start_point": {"lon": -6.055, "lat": 37.325},
      "end_point": {"lon": -6.056, "lat": 37.326}
    },
    "attempt_count": 1,
    "latency_ms": 10,
    "latency_ms_total": 10,
    "verification": {
      "status": "verified",
      "observed": true,
      "reason": "Evaluated equals on path 'data.path_found'."
    }
  }
]
```

---

# Inspeccionar verificaciones

Cada step tool puede tener un bloque `verification`.

Estados posibles:

* `verified`
* `refuted`
* `inconclusive`
* `not_evaluated`

Ejemplo:

```python id="6upm4l"
step = run.output_json["executed_outputs"][0]
step["verification"]["status"]
```

Ejemplo de lectura:

```python id="3l1v5a"
if step["verification"]["status"] == "verified":
    print("Hipótesis confirmada")
```

---

# Inspeccionar el historial de plan

```python id="4m14m0"
run.output_json["plan_history"]
```

Esto incluye el plan inicial y, si hubo replan, los planes posteriores.

Ejemplo:

```json id="7asw6k"
[
  {
    "label": "initial",
    "steps": [
      {"id": "s1", "type": "tool", "name": "spatial.network_trace"},
      {"type": "final"}
    ]
  }
]
```

---

# Leer los pasos persistidos

El runner guarda pasos técnicos en `RunStep`.

```python id="s4a0k5"
from agents_core.models import RunStep

steps = RunStep.objects.filter(run=run).order_by("idx")
for s in steps:
    print(s.idx, s.kind, s.name)
```

Esto sirve para:

* debugging
* auditoría
* observabilidad
* reconstrucción del ciclo

---

# Ejemplo de run multi-step con referencias

```python id="wtk9is"
run = Run.objects.create(
    agent=agent,
    user=user,
    input_json={
        "goal": "Busca elementos cercanos al primer punto de la capa",
        "map_context": {
            "bbox": {
                "west": -6.06,
                "south": 37.32,
                "east": -6.05,
                "north": 37.33
            },
            "zoom": 18
        }
    }
)
run = execute_run(run)
```

Un plan interno posible sería:

```json id="u48j8w"
{
  "steps": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.query_layer",
      "args": {
        "layer": "demo_points",
        "bbox": {
          "west": -6.06,
          "south": 37.32,
          "east": -6.05,
          "north": 37.33
        }
      }
    },
    {
      "id": "s2",
      "type": "tool",
      "name": "spatial.nearby",
      "depends_on": ["s1"],
      "args": {
        "layer": "demo_points",
        "point": "$step:s1.data.features.0.centroid",
        "radius_m": 100
      }
    },
    {
      "type": "final"
    }
  ]
}
```

---

# Ejemplo de step con verificación

```json id="b10mi0"
{
  "id": "s1",
  "type": "tool",
  "name": "spatial.network_trace",
  "hypothesis": "Existe una ruta válida entre los dos puntos",
  "verification_target": "Comprobar si path_found es true",
  "success_criteria": {
    "path": "data.path_found",
    "equals": true
  },
  "args": {
    "layer": "demo_lines",
    "start_point": {"lon": -6.055, "lat": 37.325},
    "end_point": {"lon": -6.056, "lat": 37.326}
  }
}
```

---

# Ejecutar un tool_call directo

El runner también puede aceptar una llamada directa a una tool dentro de `input_json`.

```python id="5q2a0z"
run = Run.objects.create(
    agent=agent,
    user=user,
    input_json={
        "tool_call": {
            "name": "spatial.query_layer",
            "args": {
                "layer": "demo_points",
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33
                }
            }
        }
    }
)

run = execute_run(run)
print(run.output_json)
```

Este modo es útil para:

* tests
* debugging
* validación directa de tools
* integraciones simples

---

# Uso vía API

## Crear run

```bash id="bex1pb"
curl -X POST http://localhost:8000/api/agents/runs/ \
  -H "Authorization: Token TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": 1,
    "input_json": {
      "goal": "Traza una ruta por la red",
      "map_context": {
        "bbox": {
          "west": -6.06,
          "south": 37.32,
          "east": -6.05,
          "north": 37.33
        },
        "zoom": 18
      }
    }
  }'
```

## Ejecutar run

```bash id="hb7frt"
curl -X POST http://localhost:8000/api/agents/runs/42/execute/ \
  -H "Authorization: Token TU_TOKEN"
```

## Consultar trace

```bash id="s07c0c"
curl http://localhost:8000/api/agents/runs/42/trace/ \
  -H "Authorization: Token TU_TOKEN"
```

## Consultar steps

```bash id="7puctk"
curl http://localhost:8000/api/agents/runs/42/steps/ \
  -H "Authorization: Token TU_TOKEN"
```

---

# Ejecutar tests

## Tests del core

```bash id="if8n0o"
python manage.py test agents_core.tests
```

## Tests de API

```bash id="6h6zpo"
python manage.py test agents_core.tests_api
```

# Ejemplos oficiales y regresión manual

GeoAgents incluye una pequeña batería oficial de ejemplos reproducibles para:

- demo
- QA
- onboarding
- validación manual tras cambios internos

Documentación asociada:

```text
docs/examples.md
docs/manual_regression.md
```

## Suite completa

```bash id="db1jnt"
python manage.py test
```

---

# Extender el sistema

## Nueva tool

Implementación típica en:

```text id="qh3owg"
agents_gis/
```

según el tipo de tool.

## Nuevas heurísticas

* `agents_llm/plan_postprocessor.py`
* futura capa de heurísticas si se separa del postprocessor

## Nuevas inferencias

```text id="hlrrj7"
agents_gis/inference.py
```

## Nuevos ejemplos

```text id="pnm1gh"
agents_llm/examples.py
examples/
```

---

# Buenas prácticas

* limitar tools por agente
* usar postprocessor para completar args
* mantener tools deterministas
* usar outputs estructurados y verificables
* no tratar `final_text` como sustituto del trace
* inspeccionar `verification_summary` cuando una hipótesis importe
* usar `steps` y `trace` para debugging serio

