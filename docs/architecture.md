# GeoAgents Architecture

GeoAgents es un **framework de agentes de inteligencia artificial especializados en análisis geoespacial (GIS)**.

El objetivo del framework es permitir que agentes IA puedan:

* interpretar preguntas espaciales
* seleccionar herramientas GIS automáticamente
* ejecutar análisis espaciales
* verificar hipótesis sobre los resultados
* sintetizar resultados en lenguaje natural

El framework está diseñado para ser:

* modular
* reproducible
* seguro
* observable
* extensible

---

# Arquitectura general

El flujo completo de ejecución actual es:

```text
User request
│
▼
API / Run creation
│
▼
Planner (LLM reasoning)
│
▼
Plan validation
│
▼
Plan postprocessing / normalization
│
▼
Execution runner
│
▼
Tool execution
│
▼
Verification
│
▼
Optional replan
│
▼
Synthesizer (LLM explanation)
```

En forma resumida:

```text
plan -> execute -> verify -> optional replan -> synthesize
```

---

# Componentes principales

El framework se divide conceptualmente en cuatro áreas principales:

```text
agents_core
agents_llm
agents_gis
agents_tools
```

---

# agents_core

Contiene el motor operativo del framework.

```text
agents_core
│
├── models.py
├── runner.py
├── steps.py
├── serializers.py
├── views.py
└── urls.py
```

## models

Define las entidades persistentes principales, especialmente:

* `Agent`
* `Run`
* `RunStep`

Estas permiten:

* persistir ejecuciones
* auditar el ciclo del agente
* exponer resultados por API
* reproducir análisis

## runner

Es la pieza central del ciclo de ejecución.

Responsabilidades principales:

* arrancar el run
* invocar al planner
* validar límites operativos
* ejecutar steps tool
* resolver referencias entre pasos
* aplicar retries y control básico de ejecución
* evaluar verificaciones
* lanzar replans cuando aplica
* invocar al synthesizer
* guardar resultado final en `Run`

El runner es quien convierte una configuración de agente en una ejecución real.

## steps

Persistencia y logging técnico del ciclo.

Cada paso significativo del proceso queda reflejado en `RunStep`, por ejemplo:

* `run.start`
* `llm.plan`
* `llm.replan`
* `llm.synthesize`
* `planner.result`
* `run.end`
* errores de ejecución

Esto aporta:

* observabilidad
* trazabilidad
* debugging
* análisis post-mortem

## serializers / views / urls

Exponen el contrato HTTP del framework.

Actualmente la API permite:

* listar agentes
* crear runs
* ejecutar runs
* consultar pasos persistidos
* consultar trace completo

---

# agents_llm

Contiene la lógica LLM del sistema.

```text
agents_llm
│
├── client.py
├── planner.py
├── plan_postprocessor.py
├── synthesizer.py
├── schemas.py
└── examples.py
```

## planner

Responsable de convertir una petición en un plan estructurado.

El planner no ejecuta nada. Devuelve JSON con steps.

Ejemplo mínimo:

```json
{
  "steps": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.intersects",
      "args": {
        "source_layer": "demo_points",
        "target_layer": "demo_polygons"
      }
    },
    {
      "type": "final"
    }
  ]
}
```

El planner puede incluir además:

* `required`
* `depends_on`
* `on_fail`
* `hypothesis`
* `verification_target`
* `success_criteria`
* `timeout_s`
* `max_retries`
* `retry_backoff_s`
* `can_replan`

## validate_plan

La validación del plan garantiza que el contrato sea correcto.

Verifica, entre otras cosas:

* estructura JSON
* tipos de step válidos
* unicidad de ids
* dependencias válidas
* tools permitidas
* semántica básica de `success_criteria`

## plan_postprocessor

Es una de las piezas clave del framework.

Responsabilidades:

* completar parámetros faltantes
* inyectar `bbox` o `zoom` cuando procede
* inferir capas GIS automáticamente
* corregir o normalizar argumentos
* aplicar reglas heurísticas
* eliminar redundancia
* adaptar el plan según el perfil del agente

## synthesizer

Genera la respuesta final en lenguaje natural.

Consume:

* facts derivados de tools
* facts estructurados
* outputs ejecutados
* verification summary
* goal original

Produce:

```text
final_text
```

La síntesis debe respetar lo realmente verificado. No debe inventar relaciones espaciales no demostradas.

---

# agents_tools

Gestiona la capa de tools del framework.

```text
agents_tools
│
├── base.py
├── registry.py
├── executor.py
├── introspection.py
└── models.py
```

## registry

Registro de tools disponibles.

## executor

Invoca tools concretas y devuelve resultados homogéneos al runner.

## introspection

Expone catálogo de tools para planner y validación.

Esta capa desacopla el motor agente del dominio GIS concreto.

---

# agents_gis

Contiene lógica específica GIS.

```text
agents_gis
│
├── inference.py
├── introspection.py
├── service.py
├── tools_query.py
├── tools_nearby.py
├── tools_intersects.py
├── tools_context.py
├── tools_network_trace.py
└── ...
```

## inference

Responsable de inferir capas GIS automáticamente.

Ejemplos típicos:

* inferir capa de puntos
* inferir capa de líneas
* inferir capa de polígonos
* detectar pares razonables para intersección

## GIS tools

Aquí vive la lógica espacial real.

Ejemplos actuales:

* `spatial.query_layer`
* `spatial.nearby`
* `spatial.intersects`
* `spatial.context_pack`
* `spatial.network_trace`

---

# GIS Layer Catalog

GeoAgents utiliza un catálogo de capas para no depender de nombres inventados por el LLM.

Ejemplo conceptual:

```json
[
  {
    "name": "demo_points",
    "table": "demo_points",
    "geometry_kind": "point"
  },
  {
    "name": "demo_lines",
    "table": "demo_lines",
    "geometry_kind": "line"
  },
  {
    "name": "demo_polygons",
    "table": "demo_polygons",
    "geometry_kind": "polygon"
  }
]
```

Este catálogo permite:

* inferencia automática
* validación de capas
* selección más robusta de tools
* reducción de errores del planner

---

# Lifecycle de un Run

Cada ejecución se guarda como un `Run`.

Conceptualmente contiene:

```text
input_json
plan
plan_history
executed_outputs
verification_summary
final_text
error
timestamps
```

Y además genera múltiples `RunStep`.

---

# Modelo lógico de ejecución

## 1. Create run

El cliente crea un `Run` con:

* `agent`
* `input_json`

## 2. Plan

El planner genera un plan inicial.

## 3. Normalize

El plan se valida y se normaliza.

## 4. Execute

El runner ejecuta los steps tool.

## 5. Verify

Cada step puede ser evaluado con `success_criteria`.

Estados de verificación posibles:

* `verified`
* `refuted`
* `inconclusive`
* `not_evaluated`

## 6. Replan

Si un paso lo permite y la evidencia lo justifica, puede haber replanificación.

## 7. Synthesize

El sintetizador genera `final_text`.

## 8. Persist trace

El resultado queda accesible tanto en `Run` como en `RunStep`.

---

# Referencias entre pasos

GeoAgents soporta referencias explícitas entre outputs previos y args posteriores.

Formato:

```text
$step:<step_id>.<campo>
```

Ejemplo:

```text
$step:s1.data.features.0.centroid
```

Esto convierte el plan en un pipeline encadenado y no en una secuencia aislada de tools.

---

# Verificación de hipótesis

Un avance importante de Fase 1.5 es que el plan y el runner ya soportan hipótesis verificables.

Ejemplo:

```json
{
  "id": "s1",
  "type": "tool",
  "name": "spatial.network_trace",
  "hypothesis": "Existe una ruta válida",
  "verification_target": "Comprobar si path_found es verdadero",
  "success_criteria": {
    "path": "data.path_found",
    "equals": true
  }
}
```

Esto permite que la arquitectura no solo ejecute, sino que también evalúe.

---

# Observabilidad y trace

El framework ya no es una caja negra.

Puede exponer por API:

* run serializado
* plan history
* executed outputs
* verification summary
* persisted steps
* trace agregado
* estadísticas de ejecución

Esto es crítico para:

* depuración
* demos
* QA
* evolución del framework

---

# Qué está cerrado en Fase 1.5

Con el estado actual del proyecto, la Fase 1.5 puede considerarse cerrada cuando existen:

* razonamiento multi-tool
* referencias entre pasos
* verificación por step
* replan básico
* trace API
* tests unitarios
* tests API
* documentación y ejemplos alineados

---

# Qué viene después

Las siguientes fases naturales ya no pertenecen al core mínimo del agente, sino a su consolidación como sistema:

* memoria de run
* memoria episódica
* heurísticas reutilizables
* budgets por run
* timeouts más duros
* retries más finos
* paralelización de ramas
* selección adaptativa de tools
