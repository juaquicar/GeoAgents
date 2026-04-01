# SET_LLAMADAS — spatial.network_service_area

> **Nota sobre `final_text`:**
> El flujo con `tool_call` directo **nunca llama al LLM** — ejecuta el tool y devuelve datos crudos, `final_text` siempre es `""`.
> Para obtener `final_text` hay que usar el flujo con `goal` (sin `tool_call`): planificador → tool → sintetizador.
> Los casos 2–7 son para verificar el comportamiento del tool de forma aislada.
> Los casos 8–10 son el flujo real con síntesis LLM.

---

## 0. Variables de entorno

```bash
export TOKEN=1c794d1b131d8f11f678176176ca13cab6af7518
export AGENT_ID=1   # ajusta al id real del agente
```

---

## 1. Habilitar el tool en el agente

```bash
curl -X PATCH http://127.0.0.1:8000/api/agents/$AGENT_ID/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d '{
    "tool_allowlist": [
      "utils.ping",
      "utils.now",
      "spatial.summary",
      "spatial.query_layer",
      "spatial.nearby",
      "spatial.intersects",
      "spatial.context_pack",
      "spatial.network_trace",
      "spatial.route_cost",
      "spatial.network_service_area"
    ]
  }'
```

---

## BLOQUE A — Flujo directo (tool_call) · sin LLM · sin final_text

Los siguientes casos ejecutan el tool directamente, sin planificador ni sintetizador.
Útiles para verificar la lógica del tool de forma aislada.

---

### 2. Cobertura parcial por coste

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"calcular area de servicio de red\",
      \"tool_call\": {
        \"name\": \"spatial.network_service_area\",
        \"args\": {
          \"layer\": \"demo_lines\",
          \"origin_point\": {\"lon\": -6.055, \"lat\": 37.325},
          \"max_cost\": 300,
          \"metric\": \"cost\",
          \"include_geom\": true,
          \"max_snap_distance_m\": 250,
          \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33}
        }
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `reachable: true`, `reachable_segment_ids`, `coverage_summary.segment_coverage_ratio` < 1.

---

### 3. Cobertura total — sin max_cost

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"cobertura total de la red\",
      \"tool_call\": {
        \"name\": \"spatial.network_service_area\",
        \"args\": {
          \"layer\": \"demo_lines\",
          \"origin_point\": {\"lon\": -6.055, \"lat\": 37.325},
          \"metric\": \"cost\",
          \"include_geom\": false,
          \"max_snap_distance_m\": 250,
          \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33}
        }
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `coverage_summary.segment_coverage_ratio == 1.0`.

---

### 4. Multiplicadores de coste por tipo de segmento

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"cobertura con coste por tipo\",
      \"tool_call\": {
        \"name\": \"spatial.network_service_area\",
        \"args\": {
          \"layer\": \"demo_lines\",
          \"origin_point\": {\"lon\": -6.055, \"lat\": 37.325},
          \"max_cost\": 300,
          \"metric\": \"cost\",
          \"length_weight\": 1.0,
          \"segment_type_costs\": {\"fiber\": 0.5, \"duct\": 1.0, \"slow\": 2.0},
          \"include_geom\": false,
          \"max_snap_distance_m\": 250,
          \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33}
        }
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** los segmentos `fiber` se alcanzan antes que los `slow` con el mismo presupuesto.

---

### 5. Segmento prohibido (restrictions)

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"cobertura evitando tramo 3\",
      \"tool_call\": {
        \"name\": \"spatial.network_service_area\",
        \"args\": {
          \"layer\": \"demo_lines\",
          \"origin_point\": {\"lon\": -6.055, \"lat\": 37.325},
          \"max_cost\": 500,
          \"metric\": \"cost\",
          \"restrictions\": {\"forbidden_segment_ids\": [3]},
          \"include_geom\": false,
          \"max_snap_distance_m\": 250,
          \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33}
        }
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `3` no aparece en `reachable_segment_ids`.

---

### 6. Snap fallido — origen fuera de red

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"cobertura desde origen muy alejado\",
      \"tool_call\": {
        \"name\": \"spatial.network_service_area\",
        \"args\": {
          \"layer\": \"demo_lines\",
          \"origin_point\": {\"lon\": -6.20, \"lat\": 37.10},
          \"max_cost\": 300,
          \"metric\": \"cost\",
          \"max_snap_distance_m\": 20,
          \"include_geom\": false,
          \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33}
        }
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `reachable: false`, `reason: "snap_distance_exceeded"`.

---

### 7. Por distancia (metric: length)

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"cobertura por distancia maxima\",
      \"tool_call\": {
        \"name\": \"spatial.network_service_area\",
        \"args\": {
          \"layer\": \"demo_lines\",
          \"origin_point\": {\"lon\": -6.055, \"lat\": 37.325},
          \"metric\": \"length\",
          \"max_distance_m\": 200,
          \"include_geom\": false,
          \"max_snap_distance_m\": 250,
          \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33}
        }
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `limits.max_distance_m == 200`.

---

## BLOQUE B — Flujo con LLM · planificador + sintetizador · final_text poblado

Los siguientes casos usan `goal` sin `tool_call`. El runner llama al planificador LLM,
ejecuta los steps que decida, y luego llama al sintetizador para generar `final_text`.

---

### 8. Cobertura de red — análisis básico

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"Analiza qué área de la red es alcanzable desde el nodo central y resume la cobertura\",
      \"map_context\": {
        \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33},
        \"zoom\": 16
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `final_text` no vacío, `executed_outputs` con al menos un step de `spatial.network_service_area`.

---

### 9. Cobertura con restricción — descripción en lenguaje natural

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"Calcula el área de cobertura de red desde el nodo central evitando el tramo 3 y explica qué zonas quedan fuera\",
      \"map_context\": {
        \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33},
        \"zoom\": 16
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `final_text` menciona la restricción, `executed_outputs[0].data.reachable_segment_ids` no incluye el 3.

---

### 10. Cobertura de red con coste por tipo de fibra

```bash
curl -X POST http://127.0.0.1:8000/api/runs/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $TOKEN" \
  -d "{
    \"agent\": $AGENT_ID,
    \"input_json\": {
      \"goal\": \"Qué tramos de red son alcanzables desde el origen con un presupuesto de despliegue de 300 unidades, considerando que la fibra tiene coste reducido\",
      \"map_context\": {
        \"bbox\": {\"west\": -6.06, \"south\": 37.32, \"east\": -6.05, \"north\": 37.33},
        \"zoom\": 16
      }
    }
  }"

export RUN_ID=<id>
curl -X POST http://127.0.0.1:8000/api/runs/$RUN_ID/execute/ \
  -H "Authorization: Token $TOKEN"
```

**Qué verificar:** `final_text` no vacío con resumen de cobertura, `executed_outputs` poblado.

---

## 11. Inspección de steps y trace (aplica a cualquier run)

```bash
# Steps — secuencia de eventos del run
curl http://127.0.0.1:8000/api/runs/$RUN_ID/steps/ \
  -H "Authorization: Token $TOKEN"

# Trace completo
curl http://127.0.0.1:8000/api/runs/$RUN_ID/trace/ \
  -H "Authorization: Token $TOKEN"
```

**En steps del flujo LLM (casos 8–10) deben aparecer:**
`run.start` → `llm.plan` → `tool.call` → `tool.result` → `llm.synthesize` → `planner.result` → `run.end`

**En trace verificar:** `trace.goal`, `trace.replan_count`, `trace.verification_summary.counts`, `trace.stats.tool_steps_executed`.
