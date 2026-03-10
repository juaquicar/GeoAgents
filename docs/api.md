# GeoAgents API

Documentación resumida de endpoints REST actuales.

Base path: `/api/`

---

## Autenticación

La API usa usuarios autenticados de Django/DRF.
También está disponible endpoint de token:

- `POST /api/token/`

---

## Agents

### Listar agentes

- `GET /api/agents/`

### Crear agente

- `POST /api/agents/`

Campos relevantes:

- `name`
- `system_prompt`
- `profile` (`compact|rich|investigate`)
- `tool_allowlist`
- `is_active`

---

## Runs

### Crear run

- `POST /api/runs/`

`input_json` puede activarse en dos modos:

### 1) Modo planner

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Analiza intersecciones entre puntos y zonas",
    "map_context": {
      "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
      "zoom": 16
    }
  }
}
```

### 2) Modo tool directo

```json
{
  "agent": 1,
  "input_json": {
    "tool_call": {
      "name": "spatial.query_layer",
      "args": {"layer": "demo_points", "limit": 20}
    }
  }
}
```

### Ejecutar run

- `POST /api/runs/{id}/execute/`

### Ver pasos registrados

- `GET /api/runs/{id}/steps/`

Devuelve secuencia `RunStep` con `idx`, `kind`, `name`, `latency_ms`, `input_json`, `output_json`, `error`.

---

## Tools catalog

### Listar catálogo introspectivo de tools

- `GET /api/tools/`

Se usa para UI, validación externa y depuración de capacidades disponibles.
