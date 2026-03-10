# GeoAgents Framework Diagrams

Este documento describe visualmente la arquitectura actual de **GeoAgents** y los cambios recientes del runner:

- ejecución en dos modos (`tool_call` directo y `goal` + planner)
- planes multi-step con `id`, `depends_on`, `hypothesis`, `on_fail`
- referencias entre pasos (`$step:<id>.<path>`)
- trazabilidad completa vía `RunStep`

---

# Arquitectura completa del framework

```mermaid
flowchart TD

U[User / Client] --> API[GeoAgents API]

API --> RC[agents_core]
RC --> RUNNER[Runner]

RUNNER --> M1{Modo de ejecución}
M1 -->|tool_call| TOOLX[Tool Executor]
M1 -->|goal| PLAN[Planner LLM]

PLAN --> POST[Plan Postprocessor]
POST --> EXEC[Execution Loop]

EXEC --> REG[Tool Registry]
REG --> GIS[GIS Tools]
GIS --> OUT[Step Outputs]

OUT --> SYN[Synthesizer LLM]
SYN --> RESP[Final Response]

RUNNER --> DB[(Run / RunStep DB)]
DB --> RESP
```

---

# Pipeline de ejecución (goal + planner)

```mermaid
sequenceDiagram

participant User
participant API
participant Runner
participant Planner
participant Postprocessor
participant Executor
participant Tools
participant Synthesizer
participant DB

User->>API: POST /api/runs/ (input_json.goal)
API->>Runner: execute(run)
Runner->>Planner: plan_run(goal, catalogs)
Planner-->>Runner: raw_plan
Runner->>Postprocessor: normalize_plan(raw_plan)
Postprocessor-->>Runner: normalized_plan

loop Cada step del plan
  Runner->>Executor: invoke_tool(step)
  Executor->>Tools: validate + invoke
  Tools-->>Executor: ToolResult
  Executor-->>Runner: {ok,data,error}
  Runner->>DB: log_step(kind=tool)
end

Runner->>Synthesizer: synthesize_run(goal, plan, outputs)
Synthesizer-->>Runner: final_text
Runner->>DB: persist output_json + final_text
Runner-->>API: run succeeded/failed
API-->>User: run payload
```

---

# Pipeline alternativo (tool_call directo)

```mermaid
flowchart LR

A[input_json.tool_call] --> B[Runner]
B --> C[Validate allowlist]
C --> D[Tool Executor]
D --> E[ToolResult]
E --> F[Persist result in Run]
F --> G[run.end]
```

---

# Plan multi-step y dependencias

```mermaid
flowchart TD

S1[s1: spatial.query_layer]\nrequired=true --> S2[s2: spatial.nearby]\ndepends_on=[s1]
S2 --> S3[s3: spatial.intersects]\ndepends_on=[s1,s2]
S3 --> F[final]

R1[args usa $step:s1.data...] --> S2
R2[on_fail=continue/abort] --> S2
R3[hypothesis] --> S2
```

---

# Trazabilidad de ejecución (RunStep)

```mermaid
flowchart TD

RUN[Run] --> STEP1[run.start]
STEP1 --> STEP2[llm.plan]
STEP2 --> STEP3[tool: spatial.query_layer]
STEP3 --> STEP4[tool: spatial.nearby]
STEP4 --> STEP5[llm.synthesize]
STEP5 --> STEP6[planner.result]
STEP6 --> STEP7[run.end]

STEP3 --> META1[idx, latency_ms, error]
STEP4 --> META2[input_json/output_json]
```

Este registro ordenado permite auditoría y depuración paso a paso.
