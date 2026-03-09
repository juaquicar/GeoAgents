# GeoAgents API

La API de GeoAgents permite:

- ejecutar agentes IA
- consultar runs
- obtener resultados de análisis
- integrar el framework en aplicaciones externas

La API está diseñada para ser usada por:

- visores GIS
- aplicaciones web
- dashboards
- servicios backend

---

# Arquitectura de la API

La API sigue un modelo simple:

```

Client
│
▼
GeoAgents API
│
▼
Agent Runner
│
▼
Tools GIS
│
▼
Synthesizer

```

Los clientes envían una solicitud con un **goal** y un **map_context**, y el agente devuelve un análisis espacial.

---

# Base URL

Ejemplo:

```

/api/agents/

```

---

# Autenticación

Dependiendo de la configuración del proyecto:

- sesión Django
- token DRF
- API key
- OAuth

Ejemplo con token:

```

Authorization: Bearer <token>

```

---

# Endpoints

## Listar agentes

```

GET /api/agents/

````

### Response

```json
[
  {
    "id": 1,
    "name": "geo-agent",
    "profile": "rich",
    "is_active": true
  }
]
````

---

# Obtener un agente

```
GET /api/agents/{id}/
```

### Response

```json
{
  "id": 1,
  "name": "geo-agent",
  "profile": "rich",
  "tool_allowlist": [
    "spatial.intersects",
    "spatial.nearby",
    "spatial.query_layer",
    "spatial.context_pack"
  ]
}
```

---

# Ejecutar agente

Crea un nuevo **Run**.

```
POST /api/agents/{id}/run/
```

---

## Request

```json
{
  "goal": "Comprueba si los puntos están dentro de las zonas",
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
```

---

## Response

```json
{
  "run_id": 42,
  "status": "queued"
}
```

---

# Consultar estado de ejecución

```
GET /api/runs/{run_id}/
```

---

## Response

```json
{
  "id": 42,
  "status": "succeeded",
  "goal": "Comprueba si los puntos están dentro de las zonas",
  "final_text": "Se detectaron intersecciones entre los puntos A y B con la zona Zona 1."
}
```

---

# Obtener resultado completo

```
GET /api/runs/{run_id}/result/
```

---

## Response

```json
{
  "id": 42,
  "input": {
    "goal": "Comprueba si los puntos están dentro de las zonas"
  },
  "plan": {
    "steps": [
      {
        "type": "tool",
        "name": "spatial.intersects"
      }
    ]
  },
  "tool_results": [
    {
      "tool": "spatial.intersects",
      "intersections": 2
    }
  ],
  "final_text": "Se detectaron intersecciones entre los puntos y las zonas."
}
```

---

# Ejecutar análisis directamente

También puede existir un endpoint simplificado.

```
POST /api/analyze/
```

---

## Request

```json
{
  "agent": "geo-agent",
  "goal": "¿Qué elementos hay cerca?",
  "map_context": {
    "bbox": {
      "west": -6.06,
      "south": 37.32,
      "east": -6.05,
      "north": 37.33
    }
  }
}
```

---

## Response

```json
{
  "analysis": "Se detectaron 5 elementos cercanos en la capa demo_points."
}
```

---

# Estado de ejecución

Un run puede tener los siguientes estados.

```
queued
running
succeeded
failed
```

---

# Modelo Run

Cada ejecución crea un registro en la base de datos.

Campos principales:

```
id
agent
input_json
status
tool_results
facts
final_text
created_at
```

Esto permite:

* auditoría
* debugging
* reproducibilidad

---

# Ejemplo de integración

## JavaScript

```javascript
await fetch("/api/agents/1/run/", {
  method: "POST",
  headers: {
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    goal: "Comprueba si los puntos están dentro de las zonas",
    map_context: {
      bbox: {
        west: -6.06,
        south: 37.32,
        east: -6.05,
        north: 37.33
      }
    }
  })
})
```

---

# Ejemplo Python

```python
import requests

r = requests.post(
    "http://localhost:8000/api/agents/1/run/",
    json={
        "goal": "Analiza esta zona",
        "map_context": {
            "bbox": {...}
        }
    }
)

print(r.json())
```

---

# Buenas prácticas

* enviar siempre `bbox`
* usar zoom si está disponible
* limitar el tamaño de consultas

---

# Versionado

La API puede versionarse:

```
/api/v1/
/api/v2/
```

---

# Futuras extensiones

Posibles endpoints futuros:

```
POST /api/tools/run
POST /api/runs/{id}/cancel
GET  /api/layers
GET  /api/catalog
```

---

# Documentación interactiva

Si se usa **Django REST Framework**, se puede generar automáticamente:

```
/api/schema/
/api/docs/
```

usando:

```
drf-spectacular
```

