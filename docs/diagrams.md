# GeoAgents Framework Diagrams

Este documento describe visualmente la arquitectura de **GeoAgents**.

Los diagramas están escritos en **Mermaid**, lo que permite renderizado automático en GitHub y sistemas de documentación.

---

# Arquitectura completa del framework

Este diagrama muestra todos los componentes principales.

```mermaid
flowchart TD

A[User / Client] --> B[GeoAgents API]

B --> C[Runner]

C --> D[Planner LLM]
D --> E[Plan Validator]

E --> F[Plan Postprocessor]

F --> G[Execution Engine]

G --> H[GIS Tools]

H --> I[Tool Results]
I --> J[Facts Extraction]

J --> K[Synthesizer LLM]

K --> L[Final Response]

C --> M[(Run Database)]

M --> L
````

---

# Pipeline de ejecución

Este diagrama muestra el **pipeline interno de un run**.

```mermaid
sequenceDiagram

participant User
participant API
participant Runner
participant Planner
participant Validator
participant Postprocessor
participant Engine
participant Tools
participant Synthesizer

User->>API: POST /agents/{id}/run
API->>Runner: create Run

Runner->>Planner: generate_plan(goal)

Planner-->>Runner: raw_plan

Runner->>Validator: validate_plan
Validator-->>Runner: validated_plan

Runner->>Postprocessor: normalize_plan
Postprocessor-->>Runner: normalized_plan

Runner->>Engine: execute_plan

Engine->>Tools: run tool
Tools-->>Engine: results

Engine-->>Runner: tool_results

Runner->>Synthesizer: build_final_text

Synthesizer-->>Runner: final_text

Runner-->>API: run completed

API-->>User: response
```

---

# Planner → Tools interaction

Este diagrama explica cómo el **planner decide qué tools usar**.

```mermaid
flowchart TD

A[User Goal]

A --> B[Planner LLM]

B --> C{Which spatial task?}

C -->|Intersection| D[spatial.intersects]

C -->|Nearby search| E[spatial.nearby]

C -->|Layer exploration| F[spatial.query_layer]

C -->|General spatial context| G[spatial.context_pack]

D --> H[Execution Engine]
E --> H
F --> H
G --> H
```

---

# Arquitectura interna del Agent

Este diagrama muestra los componentes de un agente.

```mermaid
flowchart TD

Agent[Agent]

Agent --> Prompt[System Prompt]

Agent --> Profile[Agent Profile]

Agent --> Tools[Tool Allowlist]

Profile --> Compact
Profile --> Rich
Profile --> Investigate
```

Los perfiles modifican el comportamiento del postprocessor.

---

# Plan Postprocessor Logic

Este diagrama explica el papel del **postprocessor**, que es una de las piezas clave del framework.

```mermaid
flowchart TD

RawPlan[Planner Output]

RawPlan --> Validate[Plan Validation]

Validate --> InjectContext[Inject Map Context]

InjectContext --> InferLayers[Infer GIS Layers]

InferLayers --> NormalizeArgs[Normalize Tool Args]

NormalizeArgs --> ApplyRules[Apply Goal Rules]

ApplyRules --> RemoveRedundancy[Remove Redundant Steps]

RemoveRedundancy --> FinalPlan[Normalized Plan]
```

---

# GIS Layer Inference

El sistema puede inferir capas automáticamente.

```mermaid
flowchart TD

Goal[User Goal]

Goal --> DetectKeywords

DetectKeywords -->|points| PointLayer
DetectKeywords -->|zones| PolygonLayer
DetectKeywords -->|lines| LineLayer

PointLayer --> LayerCatalog
PolygonLayer --> LayerCatalog
LineLayer --> LayerCatalog

LayerCatalog --> SelectedLayer
```

Esto permite que el agente **no tenga que conocer los nombres exactos de las capas**.

---

# Tool Execution Engine

El execution engine ejecuta los pasos del plan.

```mermaid
flowchart TD

Plan[Normalized Plan]

Plan --> Step1
Step1 --> Tool1[Execute Tool]

Tool1 --> Result1

Result1 --> Facts1

Facts1 --> NextStep

NextStep --> Tool2

Tool2 --> Result2

Result2 --> Facts2

Facts2 --> Synthesizer
```

---

# Synthesizer Architecture

El synthesizer convierte los resultados en texto.

```mermaid
flowchart TD

ToolResults --> Facts

Facts --> Context

Context --> LLM

LLM --> Response

Response --> FinalText
```

El synthesizer utiliza:

* facts estructurados
* resultados de tools
* el goal original

---

# Component Map (similar a frameworks OSS)

Este diagrama muestra la arquitectura del framework como sistema modular.

```mermaid
flowchart LR

subgraph Client
A[Web App]
B[GIS Viewer]
C[API Client]
end

subgraph GeoAgents
D[API Layer]
E[Runner]
F[Planner]
G[Validator]
H[Postprocessor]
I[Execution Engine]
J[Synthesizer]
end

subgraph GIS
K[Layer Catalog]
L[GIS Tools]
M[PostGIS]
end

A --> D
B --> D
C --> D

D --> E

E --> F
E --> G
E --> H
E --> I
E --> J

I --> L
L --> M

H --> K
```

---

# Conceptual Comparison

GeoAgents se sitúa en la siguiente categoría de frameworks.

```mermaid
flowchart LR

LangChain --> Agents
LlamaIndex --> RetrievalAgents
Haystack --> NLPipelines

GeoAgents --> SpatialAgents

SpatialAgents --> GISAnalysis
SpatialAgents --> SpatialTools
SpatialAgents --> GeospatialReasoning
```

GeoAgents introduce **razonamiento geoespacial estructurado**.

---

# Resumen conceptual

```mermaid
flowchart TD

Goal[User Goal]

Goal --> Reasoning[Planner Reasoning]

Reasoning --> Plan

Plan --> Execution

Execution --> SpatialAnalysis

SpatialAnalysis --> Facts

Facts --> Explanation

Explanation --> FinalAnswer
```

---

# Conclusión

GeoAgents combina:

* agentes IA
* herramientas GIS
* inferencia espacial
* síntesis explicativa

para crear un **motor de análisis geoespacial autónomo y extensible**.

