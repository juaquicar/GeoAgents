# GeoAgents Usage Guide

Guía práctica actualizada para crear agentes y ejecutar runs con el flujo nuevo.

---

## 1) Crear un agente

```python
from agents_core.models import Agent

agent = Agent.objects.create(
    name="geo-agent",
    system_prompt="Eres un experto en análisis espacial.",
    profile="rich",
    tool_allowlist=[
        "spatial.summary",
        "spatial.context_pack",
        "spatial.query_layer",
        "spatial.nearby",
        "spatial.intersects",
    ],
)
```

---

## 2) Crear y ejecutar un run (modo planner)

```python
from agents_core.models import Run
from agents_core.runner import execute_run

run = Run.objects.create(
    agent=agent,
    input_json={
        "goal": "Comprueba si los puntos están dentro de las zonas",
        "map_context": {
            "bbox": {
                "west": -6.06,
                "south": 37.32,
                "east": -6.05,
                "north": 37.33,
            },
            "zoom": 18,
        },
    },
)

execute_run(run)
print(run.status, run.final_text)
```

---

## 3) Ejecutar un tool_call directo

Útil para pruebas puntuales sin planificación LLM.

```python
run = Run.objects.create(
    agent=agent,
    input_json={
        "tool_call": {
            "name": "spatial.query_layer",
            "args": {"layer": "demo_points", "limit": 10},
        }
    },
)

execute_run(run)
print(run.output_json)
```

---

## 4) Entender planes multi-step

El planner puede devolver:

- `id` por step
- `depends_on` para dependencias
- `hypothesis` como hipótesis verificable
- `on_fail` para controlar continuidad (`abort|continue`)
- referencias `$step:<id>.<path>` en args

Ejemplo de referencia:

```json
{
  "id": "s2",
  "type": "tool",
  "name": "spatial.nearby",
  "depends_on": ["s1"],
  "args": {
    "point": "$step:s1.data.items.0.centroid",
    "radius_m": 100,
    "layer": "demo_points"
  }
}
```

---

## 5) Trazabilidad y depuración

Cada ejecución registra pasos en `RunStep`:

- `system`: inicio/fin
- `llm`: planificación y síntesis
- `tool`: llamadas reales a herramientas
- `result`: consolidación de output

Puedes inspeccionarlo por API en `GET /api/runs/{id}/steps/`.
