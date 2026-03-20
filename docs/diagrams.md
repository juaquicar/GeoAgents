# GeoAgents Framework Diagrams

Este documento describe visualmente la arquitectura de **GeoAgents**.

Los diagramas están escritos en **Mermaid**, lo que permite renderizado automático en GitHub y sistemas de documentación.

---

# Arquitectura completa del framework

Este diagrama muestra los componentes principales del framework en su estado actual.

```mermaid
flowchart TD

A[User / Client] --> B[GeoAgents API]

B --> C[Run]

C --> D[Runner]

D --> E[Planner LLM]
E --> F[Plan Validation]
F --> G[Plan Postprocessing / Normalization]

G --> H[Tool Execution]
H --> I[GIS Tools]
I --> J[Tool Outputs]

J --> K[Verification]
K --> L{Replan needed?}

L -->|Yes| E
L -->|No| M[Synthesizer LLM]

M --> N[Final Response]

D --> O[(Run Database)]
D --> P[(RunStep Database)]
```

---

# Pipeline real de un run

Este diagrama muestra el pipeline interno actual.

```mermaid
sequenceDiagram

participant User
participant API
participant Run
participant Runner
participant Planner
participant Validator
participant Postprocessor
participant Tools
participant Verify
participant Synthesizer

User->>API: POST /api/agents/runs/
API-->>User: Run queued

User->>API: POST /api/agents/runs/{id}/execute/
API->>Runner: execute_run(run)

Runner->>Planner: plan_run(goal, map_context)
Planner-->>Runner: raw_plan

Runner->>Validator: validate_plan(raw_plan)
Validator-->>Runner: validated_plan

Runner->>Postprocessor: normalize_plan(validated_plan)
Postprocessor-->>Runner: normalized_plan

Runner->>Tools: execute tool steps
Tools-->>Runner: structured outputs

Runner->>Verify: evaluate success_criteria
Verify-->>Runner: verified / refuted / inconclusive

alt Replan needed
    Runner->>Planner: replan with execution_context
    Planner-->>Runner: repaired_plan
end

Runner->>Synthesizer: synthesize_run(...)
Synthesizer-->>Runner: final_text

Runner-->>API: updated run
API-->>User: run completed
```

---

# Ciclo lógico del agente

```mermaid
flowchart LR

A[Goal] --> B[Plan]
B --> C[Execute]
C --> D[Verify]
D --> E{Need replan?}
E -->|Yes| B
E -->|No| F[Synthesize]
```

---

# Planner -> Tools interaction

Este diagrama explica cómo el planner decide qué tools usar según el objetivo.

```mermaid
flowchart TD

A[User Goal] --> B[Planner LLM]
B --> C{Which spatial task?}

C -->|Intersection| D[spatial.intersects]
C -->|Nearby search| E[spatial.nearby]
C -->|Layer exploration| F[spatial.query_layer]
C -->|General context| G[spatial.context_pack]
C -->|Network trace| H[spatial.network_trace]

D --> I[Runner]
E --> I
F --> I
G --> I
H --> I
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

Los perfiles modifican la profundidad del plan y la agresividad del análisis.

---

# Lógica del postprocessor

El postprocessor sigue siendo una de las piezas clave del framework.

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

Esto permite que el agente no tenga que conocer los nombres exactos de las capas.

---

# Referencias entre pasos

GeoAgents soporta referencias entre outputs previos y args posteriores.

```mermaid
flowchart TD

S1[Step s1: spatial.query_layer]
S1 --> O1[data.features.0.centroid]

O1 --> R[$step:s1.data.features.0.centroid]

R --> S2[Step s2: spatial.nearby]
```

Esto permite un pipeline multi-tool real y trazable.

---

# Verificación por step

```mermaid
flowchart TD

A[Tool step] --> B[Tool output]
B --> C[success_criteria]
C --> D{Evaluation}

D -->|Pass| E[verified]
D -->|Fail| F[refuted]
D -->|Cannot decide| G[inconclusive]
D -->|No criteria| H[not_evaluated]
```

---

# Replan básico

```mermaid
flowchart TD

A[Step executed] --> B{Failed or refuted?}
B -->|No| C[Continue]
B -->|Yes| D{can_replan and budget available?}
D -->|No| E[Abort or continue by policy]
D -->|Yes| F[Build execution_context]
F --> G[Ask planner for new plan]
G --> H[Resume execution]
```

---

# Tool execution trace

```mermaid
flowchart TD

Plan[Normalized Plan]
Plan --> Step1[Tool Step]
Step1 --> Args[Resolve args and references]
Args --> Exec[Invoke tool]
Exec --> Out[Tool output]
Out --> Verify[Verification]
Verify --> Persist[Persist RunStep / output_json]
Persist --> Next[Next step or replan]
```

---

# Trace API view

```mermaid
flowchart TD

Run[(Run)]
RunSteps[(RunStep)]
TraceSerializer[RunTraceSerializer]

Run --> TraceSerializer
RunSteps --> TraceSerializer

TraceSerializer --> TraceOutput[trace payload]

TraceOutput --> Plan[plan]
TraceOutput --> History[plan_history]
TraceOutput --> Outputs[executed_outputs]
TraceOutput --> Verification[verification_summary]
TraceOutput --> Stats[stats]
```

---

# Synthesizer Architecture

El synthesizer convierte los resultados en texto.

```mermaid
flowchart TD

ToolResults --> Facts
Facts --> StructuredFacts
StructuredFacts --> VerificationSummary
VerificationSummary --> Context
Context --> LLM
LLM --> Response
Response --> FinalText
```

El synthesizer utiliza:

* facts estructurados
* resultados de tools
* verification summary
* el goal original

---

# Component map

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
G[Validation]
H[Postprocessor]
I[Verification]
J[Synthesizer]
K[Trace API]
end

subgraph GIS
L[Layer Catalog]
M[GIS Tools]
N[PostGIS]
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
E --> K

H --> L
E --> M
M --> N
```

---

# Conceptual positioning

GeoAgents se sitúa conceptualmente en la siguiente categoría.

```mermaid
flowchart LR

LangChain --> Agents
LlamaIndex --> RetrievalAgents
Haystack --> NLPipelines

GeoAgents --> SpatialAgents

SpatialAgents --> GISAnalysis
SpatialAgents --> SpatialTools
SpatialAgents --> GeospatialReasoning
SpatialAgents --> VerifiableSpatialWorkflows
```

GeoAgents introduce razonamiento geoespacial estructurado con verificación y trazabilidad.

---

# Resumen conceptual

```mermaid
flowchart TD

Goal[User Goal]
Goal --> Reasoning[Planner Reasoning]
Reasoning --> Plan[Plan]
Plan --> Execution[Execution]
Execution --> Verification[Verification]
Verification --> Replan{Optional Replan}
Replan -->|Yes| Plan
Replan -->|No| Explanation[Explanation]
Explanation --> FinalAnswer[Final Answer]
```

---

# Conclusión

GeoAgents combina:

* agentes IA
* herramientas GIS
* inferencia espacial
* verificación de hipótesis
* síntesis explicativa
* trazabilidad operativa

para crear un **motor de análisis geoespacial autónomo, trazable y extensible**.
