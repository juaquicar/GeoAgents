# GeoAgents Examples

Este documento reúne los **ejemplos oficiales** y sirve como punto de entrada rápido para:

* demos del framework
* pruebas manuales
* onboarding técnico
* validación funcional del ciclo del agente

Los ejemplos están pensados como **fixtures conceptuales** del framework. No son solo payloads de API: representan comportamientos canónicos que GeoAgents debe seguir conservando.

---

# Objetivos de los ejemplos oficiales

Los ejemplos cubren tres capacidades clave del framework:

1. **consulta simple de capa**
2. **workflow multi-tool con referencias**
3. **hipótesis refutada con replan**

Con estos tres casos se cubren los bloques más importantes:

* planificación
* ejecución
* referencias entre pasos
* verificación
* replan básico
* trace y observabilidad

---

# Ubicación de los ejemplos

Los ejemplos oficiales viven en dos sitios distintos y complementarios.

## 1) Ejemplos usados por el planner

Se reutilizan como ejemplos canónicos del sistema en:

```text
examples/canonical_plans.py
```

Estos ejemplos pueden ser inyectados en el prompt del planner junto a los ejemplos base de `agents_llm/examples.py`.

## 2) Payloads reproducibles

Los payloads de entrada viven en:

```text
examples/01_simple_layer_query.json
examples/02_multi_tool_with_references.json
examples/03_refuted_hypothesis_with_replan.json
```

Estos archivos se pueden usar directamente con `curl`, Postman o cualquier cliente HTTP.

---

# Caso 1 — Consulta simple de capa

## Objetivo

Validar el flujo mínimo del framework.

Este caso comprueba:

* creación de run
* ejecución simple
* plan con una sola tool
* trazabilidad básica
* ausencia de replan

## Payload

Archivo:

```text
examples/01_simple_layer_query.json
```

Contenido esperado:

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

## Comportamiento esperado

Plan típico:

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

Resultados esperados:

* `status = "succeeded"`
* `replan_count = 0`
* `plan_history` con un único plan
* `executed_outputs` con un único step tool
* `trace.stats.tool_steps_executed = 1`

## Qué mirar en `trace`

* `trace.plan`
* `trace.plan_history`
* `trace.replan_count`
* `trace.executed_outputs[0].name`
* `trace.executed_outputs[0].attempt_count`
* `trace.executed_outputs[0].verification.status`
* `trace.executed_outputs[0].verification.reason`

---

# Caso 2 — Workflow multi-tool con referencias

## Objetivo

Validar que GeoAgents puede encadenar pasos y resolver referencias entre outputs previos y argumentos posteriores.

Este caso comprueba:

* razonamiento multi-step
* dependencia explícita entre pasos
* resolución de `$step:...`
* consistencia de `resolved_args`

## Payload

Archivo:

```text
examples/02_multi_tool_with_references.json
```

Contenido esperado:

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

## Comportamiento esperado

Plan típico:

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

Resultados esperados:

* `status = "succeeded"`
* `executed_outputs` con dos steps tool o más
* el segundo step depende del primero
* `resolved_args.point` aparece ya resuelto, no como string `$step:...`

## Qué mirar en `trace`

* `trace.plan.steps`
* `trace.executed_outputs[0].name`
* `trace.executed_outputs[1].name`
* `trace.executed_outputs[1].depends_on`
* `trace.executed_outputs[1].resolved_args`
* `trace.verification_summary`

Punto crítico:

`resolved_args` debe contener el valor final resuelto y no la referencia textual.

---

# Caso 3 — Hipótesis refutada con replan

## Objetivo

Validar el ciclo de verificación y replan básico.

Este caso comprueba:

* `success_criteria`
* evaluación de hipótesis
* estado `refuted`
* incremento de `replan_count`
* historial de planes (`plan_history`) con más de una versión

## Payload

Archivo:

```text
examples/03_refuted_hypothesis_with_replan.json
```

Contenido esperado:

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

## Comportamiento esperado

Plan inicial típico:

```json
{
  "steps": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.network_trace",
      "success_criteria": {
        "path": "data.path_found",
        "equals": true
      },
      "can_replan": true
    },
    {
      "type": "final"
    }
  ]
}
```

## Nota importante

Este caso depende del dataset o del entorno de prueba.

Si el dataset real sí contiene una ruta válida, la hipótesis no quedará refutada. Por eso este ejemplo funciona mejor como:

* caso controlado en QA
* dataset preparado
* demo con mocks
* fixture conceptual del planner y del runner

## Qué mirar en `trace`

* `trace.replan_count`
* `trace.plan_history`
* `trace.verification_summary.refuted`
* `trace.executed_outputs`
* `trace.stats`

Si el escenario de refutación ocurre correctamente, deberías ver:

* al menos un step con `verification.status = "refuted"`
* `replan_count >= 1`
* `plan_history` con dos planes o más

---

# Cómo ejecutar los ejemplos

## 1. Crear run

Ejemplo:

```bash
curl -X POST http://localhost:8000/api/agents/runs/ \
  -H "Authorization: Token TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/01_simple_layer_query.json
```

## 2. Ejecutar run

```bash
curl -X POST http://localhost:8000/api/agents/runs/42/execute/ \
  -H "Authorization: Token TU_TOKEN"
```

## 3. Consultar trace

```bash
curl http://localhost:8000/api/agents/runs/42/trace/ \
  -H "Authorization: Token TU_TOKEN"
```

## 4. Consultar steps persistidos

```bash
curl http://localhost:8000/api/agents/runs/42/steps/ \
  -H "Authorization: Token TU_TOKEN"
```

---

# Qué valida cada ejemplo

## Caso 1

Valida:

* flujo mínimo
* serialización básica del run
* trazabilidad simple
* ausencia de replan

## Caso 2

Valida:

* multi-tool reasoning
* referencias entre pasos
* resolución de argumentos
* encadenamiento real de outputs

## Caso 3

Valida:

* hipótesis verificables
* `success_criteria`
* refutación
* replan
* `plan_history`

---

# Uso recomendado

## Para demos

* caso 1 para enseñar el flujo más simple
* caso 2 para enseñar razonamiento multi-step
* caso 3 para enseñar verificación y replan

## Para QA

Ejecutar estos ejemplos tras cambios en:

* `planner.py`
* `plan_postprocessor.py`
* `runner.py`
* `serializers.py`
* `views.py`
* tools GIS

## Para onboarding

Pedir al nuevo desarrollador que:

1. ejecute los tres ejemplos
2. lea la salida de `trace`
3. identifique qué ha hecho el planner
4. explique cómo se resolvieron los pasos
5. localice en el código dónde vive cada responsabilidad

---

# Relación con otros documentos

Para entender completamente estos ejemplos, conviene leer también:

* `docs/architecture.md`
* `docs/api.md`
* `docs/tools.md`
* `docs/usage.md`
* `docs/manual_regression.md`

---

# Criterio de aceptación

Los ejemplos oficiales se consideran bien mantenidos si:

* siguen siendo reproducibles
* el `trace` refleja correctamente el comportamiento esperado
* el contrato externo sigue estable
* el planner sigue produciendo planes coherentes
* los pasos ejecutados siguen siendo interpretables
* las verificaciones y replans no se rompen tras cambios internos

---

# Resumen

Estos tres ejemplos oficiales son la base práctica porque demuestran que GeoAgents ya puede comportarse como un agente trazable y defendible:

* planifica
* ejecuta
* verifica
* replanifica
* sintetiza
* expone todo por API

