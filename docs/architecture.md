# GeoAgents Architecture

GeoAgents es un framework de agentes para análisis geoespacial con dos principios clave:

- **razonamiento controlado** (LLM planifica, pero no ejecuta directamente)
- **ejecución determinista y auditable** (tools tipadas + registro de pasos)

---

# Flujo general

Actualmente el `Runner` soporta dos modos:

1. **Modo directo**: `input_json.tool_call` → valida allowlist → ejecuta 1 tool.
2. **Modo planificado**: `input_json.goal` → planner/postprocessor → ejecuta plan multi-step → sintetiza.

---

# Componentes

## `agents_core`

Contiene modelos y orquestación principal:

- `Agent`: prompt, perfil (`compact|rich|investigate`) y `tool_allowlist`
- `Run`: estado, entrada/salida, texto final, errores y timestamps
- `RunStep`: traza cronológica de ejecución (`idx`, `kind`, `name`, `latency_ms`, `error`)
- `runner.execute_run`: coordina modos de ejecución, dependencias y políticas de fallo

### Novedades relevantes del runner

- Soporte de **steps con `id`** para enlazar resultados entre pasos.
- Resolución de referencias en args con patrón **`$step:<id>.<path>`**.
- Dependencias explícitas con **`depends_on`**.
- Política de error por step con **`on_fail`** (`abort` / `continue`).
- Límite de seguridad de tools por plan (`AGENTS_MAX_PLANNER_TOOL_STEPS`).

## `agents_llm`

- `planner.py`: crea plan JSON usando catálogo de tools + catálogo GIS.
- `plan_postprocessor.py`: normaliza estructura y aplica heurísticas.
- `synthesizer.py`: genera respuesta final basada en `step_outputs` reales.

## `agents_tools`

- `registry.py`: registro central de tools disponibles.
- `executor.py`: valida args, ejecuta tool y registra `RunStep(kind="tool")`.
- `introspection.py`: expone catálogo serializable para planner y API.

## `agents_gis`

Implementa tools y soporte GIS:

- `spatial.summary`
- `spatial.context_pack`
- `spatial.query_layer`
- `spatial.nearby`
- `spatial.intersects`
- `spatial.network_trace`

También mantiene inferencia de capas y catálogo GIS para restringir planes a capas válidas.

---

# Modelo de plan (actual)

Un plan puede contener steps de tool con metadatos de ejecución:

```json
{
  "steps": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.query_layer",
      "required": true,
      "hypothesis": "La capa contiene puntos en el bbox",
      "depends_on": [],
      "on_fail": "abort",
      "args": {"layer": "demo_points", "bbox": {"west": -6.06}}
    },
    { "type": "final" }
  ]
}
```

---

# Observabilidad

Cada run queda trazado en `RunStep` (sistema, llm, tool, result), lo que permite:

- depuración de errores por paso
- auditoría de decisiones del planner
- métricas de latencia por tool
