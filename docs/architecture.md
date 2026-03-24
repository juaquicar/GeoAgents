# GeoAgents Architecture

GeoAgents es un **framework de agentes de inteligencia artificial especializados en análisis geoespacial (GIS)**, con una arquitectura suficientemente general como para soportar también agentes no GIS cuando el dominio no requiera capacidades espaciales.

El objetivo del framework es permitir que agentes IA puedan:

* interpretar preguntas espaciales o analíticas
* seleccionar herramientas automáticamente
* ejecutar análisis sobre datos estructurados o geoespaciales
* verificar hipótesis sobre los resultados obtenidos
* replanificar cuando la evidencia no confirma la hipótesis inicial
* sintetizar resultados en lenguaje natural
* persistir memoria operacional y episódica reutilizable

El framework está diseñado para ser:

* modular
* reproducible
* seguro
* observable
* extensible
* trazable
* verificable

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
│
▼
Persistent run intelligence
│
├── Run memory
└── Episode memory
```

En forma resumida:

```text
plan -> execute -> verify -> optional replan -> synthesize -> persist memory
```

La arquitectura actual ya permite afirmar que GeoAgents implementa un ciclo de agente secuencial con:

* planificación
* ejecución multi-tool
* verificación de hipótesis
* replanificación básica
* trazabilidad persistida
* memoria operacional de runs
* memoria episódica derivada

---

# Componentes principales

El framework se divide conceptualmente en cuatro áreas principales:

```text
agents_core
agents_llm
agents_gis
agents_tools
```

Y una quinta capacidad transversal ya consolidada:

```text
persistent intelligence
```

Esta inteligencia persistente no vive como un módulo aislado de producto, sino como una capa de consolidación sobre `Run`, `RunStep`, `run_memory` y `episode`.

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
├── urls.py
├── heuristics.py
└── memory.py
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
* almacenar memoria derivada del comportamiento del run

En la práctica, `Run` ya no es solo un contenedor transaccional de ejecución. También es la unidad base de memoria operacional del framework.

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
* persistir inteligencia del run al finalizar

El runner es quien convierte una configuración de agente en una ejecución real, verificable y persistida.

En el estado actual, soporta dos modos principales:

* ejecución planificada a partir de `goal`
* ejecución directa de una tool vía `tool_call`

## steps

Persistencia y logging técnico del ciclo.

Cada paso significativo del proceso queda reflejado en `RunStep`, por ejemplo:

* `run.start`
* `llm.plan`
* `llm.replan.request`
* `llm.replan`
* `llm.synthesize`
* `planner.result`
* `tool.result`
* `run.end`
* errores de ejecución

Esto aporta:

* observabilidad
* trazabilidad
* debugging
* análisis post-mortem
* reconstrucción del ciclo del agente

## memory

Esta pieza consolida la inteligencia persistente del framework.

Responsabilidades principales:

* derivar memoria estructurada desde `Run`
* resumir secuencia de herramientas usadas
* clasificar dominio y tipo de análisis
* consolidar estado de verificación final
* detectar modos de fallo
* generar episodio reutilizable
* producir recomendaciones estratégicas para futuros arranques

Esta capa transforma una ejecución puntual en conocimiento operativo reutilizable.

## heuristics

Agrupa lógica heurística reutilizable para análisis de resultados, clasificación de ejecución y sugerencias de estrategia.

Esta capa no sustituye al planner, pero reduce fragilidad y permite construir comportamiento más estable sobre ejecuciones ya observadas.

## serializers / views / urls

Exponen el contrato HTTP del framework.

Actualmente la API permite:

* listar agentes
* crear runs
* ejecutar runs
* consultar pasos persistidos
* consultar trace completo
* recuperar `run_memory`
* recuperar `episode`
* filtrar runs por memoria persistida

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

Con esto, el planner deja de ser un simple generador de steps y pasa a definir un contrato verificable de ejecución.

## validate_plan

La validación del plan garantiza que el contrato sea correcto.

Verifica, entre otras cosas:

* estructura JSON
* tipos de step válidos
* unicidad de ids
* dependencias válidas
* tools permitidas
* semántica básica de `success_criteria`

La validación evita que el runner trabaje con planes estructuralmente inválidos o incoherentes.

## plan_postprocessor

Es una de las piezas clave del framework.

Responsabilidades:

* completar parámetros faltantes
* inyectar `bbox` o `zoom` cuando procede
* inyectar `trace_context` cuando procede
* inferir capas GIS automáticamente
* corregir o normalizar argumentos
* aplicar reglas heurísticas
* eliminar redundancia
* adaptar el plan según el perfil del agente

En el estado actual, esta capa es crítica para que la intención real del usuario llegue a la tool adecuada con argumentos consistentes.

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

La síntesis debe respetar lo realmente verificado. No debe inventar relaciones espaciales no demostradas ni presentar como éxito una hipótesis refutada.

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

Permite desacoplar el núcleo del framework de implementaciones concretas de tools y mantener un catálogo coherente de capacidades invocables.

## executor

Invoca tools concretas y devuelve resultados homogéneos al runner.

Su responsabilidad no es razonar, sino normalizar la interacción entre el motor agente y las tools registradas.

## introspection

Expone catálogo de tools para planner y validación.

Esta capa desacopla el motor agente del dominio GIS concreto y facilita que el framework evolucione hacia dominios mixtos.

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

## service

Contiene utilidades de acceso a datos GIS y abstracciones comunes para consulta y serialización de resultados espaciales.

## GIS tools

Aquí vive la lógica espacial real.

Ejemplos actuales:

* `spatial.query_layer`
* `spatial.nearby`
* `spatial.intersects`
* `spatial.context_pack`
* `spatial.network_trace`

Estas tools son la capa de ejecución efectiva sobre PostGIS y sobre el catálogo de capas.

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
* desacoplamiento entre lenguaje natural y estructura física de la base de datos

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
run_memory
episode
timestamps
```

Y además genera múltiples `RunStep`.

La arquitectura actual hace una distinción importante entre tres niveles:

* ejecución transaccional del run
* trace persistido del run
* memoria estructurada derivada del run

---

# Modelo lógico de ejecución

## 1. Create run

El cliente crea un `Run` con:

* `agent`
* `input_json`

El run nace en estado `queued`.

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

En el estado actual se soporta replanificación básica, con persistencia de:

* `replan_count`
* `plan_history`
* `execution_context`
* `replans`

## 7. Synthesize

El sintetizador genera `final_text`.

## 8. Persist trace

El resultado queda accesible tanto en `Run` como en `RunStep`.

## 9. Persist intelligence

Se consolidan:

* `run_memory`
* `episode`

Este paso convierte la ejecución en una unidad recuperable de experiencia del agente.

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

Uno de los avances clave del framework es que el plan y el runner soportan hipótesis verificables.

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

Esto permite que la arquitectura no solo ejecute, sino que también evalúe el resultado frente a una afirmación explícita.

La consecuencia importante es que hay dos nociones diferentes de “éxito”:

* éxito técnico de ejecución del run
* éxito analítico de la hipótesis

Eso explica casos como:

* `status = succeeded`
* `verification_status = refuted`

---

# Replanificación básica

GeoAgents ya soporta replanificación básica cuando una hipótesis queda:

* `refuted`
* `inconclusive`

o cuando una tool falla y el step permite replan.

La replanificación actual:

* incrementa `replan_count`
* genera nuevo `execution_context`
* persiste `llm.replan.request`
* persiste `llm.replan`
* añade entrada en `plan_history`

Hoy la replanificación es todavía conservadora. El framework ya registra el evento y el contexto, aunque la estrategia alternativa aún puede ser parecida a la original.

Arquitectónicamente esto ya es suficiente para afirmar que GeoAgents no es un mero executor lineal, sino un sistema con realimentación básica basada en evidencia.

---

# Memoria persistente

La fase actual ya incorpora memoria persistente en dos niveles.

## Run memory

Es la memoria operacional del run.

Resume:

* objetivo normalizado
* firma semántica del objetivo
* dominio
* tipos de análisis
* capas implicadas
* tools utilizadas
* secuencia de tools
* plan final
* plan history
* resultados estructurados
* estado de verificación
* outcome
* errores
* failure modes
* replans

Su función principal es hacer recuperable y filtrable la experiencia operacional del sistema.

## Episode

Es la memoria episódica derivada.

Resume:

* patrón de resolución seguido
* secuencia de tools
* resultado del episodio
* éxito o fracaso semántico
* modos de fallo
* evidencia agregada
* estrategia recomendada

Su función es elevar una ejecución concreta a conocimiento reutilizable por otras capas del sistema.

---

# Persistent intelligence

Esta es la capa conceptual que convierte GeoAgents en algo más que un framework de ejecución.

A partir de los runs ejecutados, el sistema ya puede:

* clasificar ejecuciones por dominio
* recuperar runs por estado de verificación
* detectar secuencias efectivas de tools
* identificar patrones de fallo
* distinguir éxito técnico de hipótesis confirmada
* sugerir estrategias futuras de arranque

Ejemplos de información persistida:

* `verification_status = verified`
* `verification_status = refuted`
* `failure_modes = ["verification_refuted"]`
* `recommended_strategy = "Secuencia efectiva detectada..."`

Esto permite hablar ya de **inteligencia persistente básica**.

---

# Observabilidad y trace

El framework ya no es una caja negra.

Puede exponer por API:

* run serializado
* plan final
* plan history
* executed outputs
* verification summary
* persisted steps
* trace agregado
* run memory
* episode
* estadísticas de ejecución

Esto es crítico para:

* depuración
* demos
* QA
* evaluación comparativa
* evolución del framework
* explicación de decisiones del agente

---

# Contrato semántico de salida

Una ejecución completa produce tres capas de salida:

## 1. Salida narrativa

* `final_text`

## 2. Salida técnica

* `output_json`
* `executed_outputs`
* `verification_summary`
* `plan_history`

## 3. Salida de memoria

* `run_memory`
* `episode`

Esta separación es importante porque evita mezclar:

* lo que el usuario debe leer
* lo que un desarrollador debe auditar
* lo que el sistema debe recordar

---

# Qué está cerrado actualmente

Con el estado actual del proyecto, ya puede considerarse consolidado lo siguiente:

* razonamiento multi-tool secuencial
* referencias entre pasos
* verificación por step
* replanificación básica
* trace API
* persistencia de `run_memory`
* persistencia de `episode`
* clasificación por `verification_status`
* filtros API sobre memoria persistida
* tests unitarios y tests de comportamiento clave

Formalmente, ya puede describirse GeoAgents como:

> un framework de agentes secuenciales con planificación, ejecución multi-tool, verificación de hipótesis, replanificación básica y trazabilidad completa, enriquecido con memoria operacional persistente y memoria episódica derivada


