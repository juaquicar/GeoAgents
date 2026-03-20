# GeoAgents Manual Regression / Demo Guide

Este documento define una batería manual pequeña y estable para:

- demos del framework
- QA funcional
- onboarding técnico
- validación rápida tras cambios en planner, runner, serializers o API

La idea es comprobar no solo que el run termina, sino que el contrato externo sigue siendo consistente y que el `trace` refleja bien el comportamiento del agente.

---

# Preparación

## Requisitos

- servidor Django levantado
- autenticación disponible
- al menos un `Agent` activo
- datasets demo cargados
- endpoints API accesibles

## Base URL de ejemplo

```text
http://localhost:8000/api/agents
````

## Header de autenticación

```text
Authorization: Token TU_TOKEN
Content-Type: application/json
```

---

# Flujo manual estándar

Cada caso se valida con este flujo:

1. crear run
2. ejecutar run
3. consultar run
4. consultar trace
5. validar salida final y contrato

Endpoints:

```text
POST /api/agents/runs/
POST /api/agents/runs/{id}/execute/
GET  /api/agents/runs/{id}/
GET  /api/agents/runs/{id}/trace/
GET  /api/agents/runs/{id}/steps/
```

---

# Caso 1 — Consulta simple de capa

## Objetivo

Validar el caso mínimo de exploración de capa.

Comprueba:

* creación y ejecución correcta del run
* plan simple de una única tool
* `executed_outputs` estable
* `trace` sin replan

## Payload de entrada

Archivo recomendado:

```text
examples/01_simple_layer_query.json
```

Payload:

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Explora la capa de puntos dentro de esta zona",
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
}
```

## Respuesta esperada

### Al crear el run

Esperado:

* HTTP `201`
* `status = "queued"`
* `replan_count = 0`
* `plan_history = []`
* `executed_outputs = []`

### Al ejecutar el run

Esperado:

* HTTP `200`
* `status = "succeeded"`
* `final_text` no vacío
* `replan_count = 0`
* al menos un elemento en `executed_outputs`

### Forma esperada del plan

El plan debería ser parecido a esto:

```json
{
  "steps": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.query_layer"
    },
    {
      "type": "final"
    }
  ]
}
```

No hace falta exigir igualdad exacta, pero sí:

* un solo step tool
* `name = "spatial.query_layer"`
* último step `final`

## Qué mirar en trace

Consultar:

```text
GET /api/agents/runs/{id}/trace/
```

Validaciones mínimas:

### `trace.plan`

* existe
* contiene un step `spatial.query_layer`

### `trace.plan_history`

* existe
* longitud esperada: `1`
* etiqueta esperada: `initial`

### `trace.replan_count`

Esperado:

```text
0
```

### `trace.executed_outputs[0]`

Debe contener claramente:

* `id`
* `type`
* `name`
* `ok`
* `attempt_count`
* `depends_on`
* `resolved_args`
* `verification.status`
* `verification.reason`

Contrato mínimo esperado:

```json
{
  "type": "tool",
  "name": "spatial.query_layer",
  "attempt_count": 1,
  "depends_on": [],
  "resolved_args": {},
  "verification": {
    "status": "verified | refuted | inconclusive | not_evaluated",
    "reason": "..."
  }
}
```

### `trace.stats`

Esperado:

* `tool_steps_executed = 1`
* `total_attempts >= 1`

---

# Caso 2 — Workflow multi-tool con referencias

## Objetivo

Validar encadenamiento de pasos y resolución de referencias `$step:...`.

Comprueba:

* plan multi-step
* dependencia explícita entre pasos
* uso de output de un paso anterior
* contrato de `resolved_args`

## Payload de entrada

Archivo recomendado:

```text
examples/02_multi_tool_with_references.json
```

Payload:

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Busca elementos cercanos al primer punto detectado dentro de esta zona",
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
}
```

## Respuesta esperada

### Al ejecutar el run

Esperado:

* HTTP `200`
* `status = "succeeded"`
* `executed_outputs` con al menos dos steps
* `final_text` no vacío

### Forma esperada del plan

Debe existir un flujo parecido a:

```json
{
  "steps": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.query_layer"
    },
    {
      "id": "s2",
      "type": "tool",
      "name": "spatial.nearby",
      "depends_on": ["s1"]
    },
    {
      "type": "final"
    }
  ]
}
```

No hace falta que sea exacto al milímetro, pero sí debe cumplirse:

* primer step tool de exploración
* segundo step tool dependiente del primero
* `depends_on = ["s1"]` o equivalente según ids reales
* uso de referencia entre pasos

## Qué mirar en trace

### `trace.plan.steps`

Validar que existen al menos dos tools.

### `trace.executed_outputs`

Validar:

* longitud mínima `2`
* primer step con `name = spatial.query_layer`
* segundo step con `name = spatial.nearby`

### `trace.executed_outputs[1].depends_on`

Esperado:

```json
["s1"]
```

o el id equivalente del paso previo.

### `trace.executed_outputs[1].resolved_args`

Aquí está una de las comprobaciones más importantes.

Debe verse que el argumento `point` ya no contiene la referencia textual, sino el valor resuelto.

Esperado conceptualmente:

```json
{
  "layer": "demo_points",
  "point": {
    "lon": -6.055,
    "lat": 37.325
  },
  "radius_m": 100
}
```

No debe quedar esto:

```text
$step:s1.data.features.0.centroid
```

### `trace.verification_summary`

Debe existir siempre, incluso si los pasos no tenían criteria complejos.

Comprobar que:

* existe `counts`
* los estados están presentes:

  * `verified`
  * `refuted`
  * `inconclusive`
  * `not_evaluated`

---

# Caso 3 — Hipótesis refutada con replan

## Objetivo

Validar ciclo de verificación y replan básico.

Comprueba:

* `success_criteria`
* estado `refuted`
* incremento de `replan_count`
* existencia de más de un plan en `plan_history`

## Payload de entrada

Archivo recomendado:

```text
examples/03_refuted_hypothesis_with_replan.json
```

Payload:

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Comprueba si existe una ruta de red válida entre dos puntos y, si no existe, inspecciona la red disponible en la zona",
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
}
```

## Respuesta esperada

Este caso tiene una aclaración importante:

El replan real depende del dataset o del entorno de prueba. En entorno demo puro, este caso puede no refutar siempre la hipótesis si la red sí conecta. Por eso este escenario es especialmente útil con mocks o datasets controlados.

### En el escenario esperado de refutación

Se espera:

* `status = "succeeded"` o `failed` controlado, según política
* al menos un step con `verification.status = "refuted"`
* `replan_count >= 1`
* `plan_history` con más de un elemento

## Qué mirar en trace

### `trace.replan_count`

Esperado:

```text
>= 1
```

### `trace.plan_history`

Esperado:

* longitud `>= 2`
* primer elemento con `label = "initial"`
* siguientes elementos tipo `replan_1`, `replan_2`, etc.

### `trace.verification_summary.refuted`

Debe existir al menos un item.

Esperado conceptualmente:

```json
{
  "id": "s1",
  "tool": "spatial.network_trace",
  "criteria": {
    "path": "data.path_found",
    "equals": true
  },
  "observed": false,
  "reason": "Evaluated equals on path 'data.path_found'."
}
```

### `trace.executed_outputs`

Debe mostrar:

* step inicial que falla o queda refutado
* uno o más steps posteriores tras replan, si aplica

### `trace.stats`

Comprobar que:

* `tool_steps_executed >= 1`
* `total_attempts >= 1`

---

# Checklist rápida de validación

## Caso 1 — simple layer query

* run creado en `queued`
* ejecución en `succeeded`
* plan con una tool
* `replan_count = 0`
* `trace.stats.tool_steps_executed = 1`

## Caso 2 — multi-tool with references

* run ejecutado correctamente
* dos tools o más
* segundo step con `depends_on`
* `resolved_args` ya resueltos
* `trace` coherente con el pipeline

## Caso 3 — refuted hypothesis with replan

* existe `success_criteria`
* existe item `refuted` o comportamiento controlado esperado
* `replan_count >= 1` en escenario controlado
* `plan_history` con más de un plan

---

# Comandos manuales sugeridos

## Crear run

```bash
curl -X POST http://localhost:8000/api/agents/runs/ \
  -H "Authorization: Token TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/01_simple_layer_query.json
```

## Ejecutar run

```bash
curl -X POST http://localhost:8000/api/agents/runs/42/execute/ \
  -H "Authorization: Token TU_TOKEN"
```

## Consultar trace

```bash
curl http://localhost:8000/api/agents/runs/42/trace/ \
  -H "Authorization: Token TU_TOKEN"
```

## Consultar steps

```bash
curl http://localhost:8000/api/agents/runs/42/steps/ \
  -H "Authorization: Token TU_TOKEN"
```

---

# Qué documentar cuando algo falla

Si una regresión aparece, registrar como mínimo:

* payload usado
* run id
* respuesta de `/runs/{id}/`
* respuesta de `/runs/{id}/trace/`
* diferencia respecto al comportamiento esperado
* si el fallo es:

  * de planner
  * de runner
  * de serializer
  * de tool
  * de synthesizer

---

# Uso recomendado de esta batería

## Para demo

Usar:

* caso 1 para mostrar flujo mínimo
* caso 2 para enseñar reasoning multi-step
* caso 3 para enseñar verificación y replan

## Para QA

Ejecutar siempre tras cambios en:

* `planner.py`
* `plan_postprocessor.py`
* `runner.py`
* `serializers.py`
* `views.py`
* tools GIS

## Para onboarding

Pedir al nuevo desarrollador que:

1. cree y ejecute los tres runs
2. lea `trace`
3. explique qué ha ocurrido en cada caso
4. identifique dónde vive cada responsabilidad en el código

---

# Criterio de aceptación de esta batería

Esta batería manual se considera válida si permite comprobar de forma rápida:

* que el framework responde
* que el contrato externo sigue estable
* que el trace refleja bien la ejecución
* que el razonamiento multi-tool sigue operativo
* que la verificación y el replan no se han roto

