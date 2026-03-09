# GeoAgents Architecture

GeoAgents es un **framework de agentes de inteligencia artificial especializados en análisis geoespacial (GIS)**.

El objetivo del framework es permitir que agentes IA puedan:

- interpretar preguntas espaciales
- seleccionar herramientas GIS automáticamente
- ejecutar análisis espaciales
- sintetizar resultados en lenguaje natural

El framework está diseñado para ser:

- modular
- reproducible
- seguro
- extensible

---

# Arquitectura general

El flujo completo de ejecución es:

```

User request
│
▼
Planner (LLM reasoning)
│
▼
Plan validation
│
▼
Plan postprocessing
│
▼
Execution engine
│
▼
Facts extraction
│
▼
Synthesizer (LLM explanation)

```

---

# Componentes principales

El framework se divide en dos módulos principales.

```

agents_core
agents_gis

```

---

# agents_core

Contiene el motor de agentes.

```

agents_core
│
├── planner.py
├── validator.py
├── plan_postprocessor.py
├── execution_engine.py
├── synthesizer.py
└── runner.py

````

### planner

Responsable de convertir una pregunta en un plan estructurado.

Ejemplo de plan:

```json
{
  "steps": [
    {
      "type": "tool",
      "name": "spatial.intersects"
    },
    {
      "type": "final"
    }
  ]
}
````

El planner **no ejecuta nada**.

Solo decide qué herramientas usar.

---

### validator

Comprueba que el plan generado por el LLM sea válido.

Verifica:

* estructura JSON correcta
* tools permitidas
* tipos de pasos válidos

---

### plan_postprocessor

Es uno de los componentes clave.

Responsabilidades:

* completar parámetros faltantes
* inferir capas GIS automáticamente
* aplicar heurísticas espaciales
* eliminar pasos redundantes
* adaptar el plan según el perfil del agente

---

### execution_engine

Ejecuta las herramientas del plan.

Flujo:

```
for step in plan:
    ejecutar tool
    guardar resultados
```

Cada tool devuelve:

```
result
facts
```

---

### synthesizer

Genera la respuesta final en lenguaje natural.

Utiliza:

* los facts de cada tool
* el contexto del run
* el objetivo del usuario

Produce:

```
final_text
```

---

### runner

Coordina todo el flujo:

```
planner
→ validator
→ postprocessor
→ execution
→ synthesizer
```

También guarda el resultado en el modelo `Run`.

---

# agents_gis

Contiene lógica específica GIS.

```
agents_gis
│
├── inference.py
├── tools/
└── catalog/
```

---

### inference

Responsable de inferir capas GIS automáticamente.

Ejemplos:

```
infer_intersection_layers
infer_nearby_layer
infer_query_layer
```

---

# GIS Layer Catalog

GeoAgents utiliza un catálogo de capas.

Ejemplo:

```
[
  {
    "name": "demo_points",
    "table": "demo_points",
    "geometry": "POINT"
  },
  {
    "name": "demo_polygons",
    "table": "demo_polygons",
    "geometry": "POLYGON"
  }
]
```

Este catálogo permite:

* inferencia automática
* validación
* evitar errores del LLM

---

# Run lifecycle

Cada ejecución se guarda como un `Run`.

Contiene:

```
input
plan
tool_results
facts
final_text
```

Esto permite:

* debugging
* auditoría
* reproducibilidad



