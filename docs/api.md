# GeoAgents API

La API de GeoAgents expone el núcleo del framework de agentes mediante recursos REST sobre:

* agentes (`agents`)
* ejecuciones (`runs`)
* trazas de ejecución (`trace`)
* pasos persistidos (`steps`)
* memoria operacional persistida dentro de cada run (`run_memory`)
* memoria episódica derivada (`episode`)

Permite:

* listar y consultar agentes disponibles
* crear ejecuciones (`Run`)
* ejecutar un run bajo demanda
* inspeccionar el resultado final
* revisar el detalle de pasos persistidos
* auditar el plan, los replans, las verificaciones y los tiempos de ejecución
* recuperar memoria estructurada de ejecuciones anteriores
* filtrar runs por estado de verificación, dominio, herramienta, capa o tipo de análisis

La API está pensada para integrarse con:

* visores GIS
* aplicaciones web
* backends
* scripts de automatización
* herramientas de debugging y observabilidad
* pipelines de evaluación y benchmarking de agentes

---

# Arquitectura de la API

El flujo real de ejecución es:

```text
Client
│
▼
GeoAgents API
│
▼
Run
│
▼
Planner
│
▼
Tool execution
│
▼
Verification / optional replan
│
▼
Synthesizer
│
▼
Persistent run intelligence
```

En términos de ciclo lógico del agente:

```text
plan -> execute -> verify -> optional replan -> synthesize -> persist memory
```

---

# Base URL

Ejemplo de prefijo:

```text
/api/agents/
```

Con el router actual, los recursos publicados son:

```text
/api/agents/agents/
/api/agents/runs/
```

Endpoints derivados relevantes:

```text
/api/agents/runs/{id}/execute/
/api/agents/runs/{id}/steps/
/api/agents/runs/{id}/trace/
```

---

# Autenticación

Los viewsets requieren autenticación y actualmente están protegidos con permisos DRF de usuario autenticado.

Según la configuración del proyecto, puede usarse:

* sesión Django
* token DRF
* otros mecanismos compatibles con DRF

Ejemplo con token DRF:

```text
Authorization: Token <token>
```

Nota: en la implementación actual, el esquema correcto documentado para token DRF es `Token`, no `Bearer`.

---

# Recursos principales

## Agent

Representa un agente configurable del framework.

Campos relevantes:

* `id`
* `name`
* `system_prompt`
* `is_active`
* `tool_allowlist`
* `profile`
* `created_at`

## Run

Representa una ejecución de un agente para un usuario concreto.

Campos relevantes:

* `id`
* `agent`
* `agent_name`
* `user`
* `status`
* `input_json`
* `output_json`
* `final_text`
* `error`
* `verification_summary`
* `replan_count`
* `plan_history`
* `executed_outputs`
* `run_memory`
* `episode`
* `created_at`
* `started_at`
* `ended_at`

## RunStep

Representa un paso persistido del ciclo de ejecución.

Campos relevantes:

* `id`
* `run`
* `idx`
* `kind`
* `name`
* `input_json`
* `output_json`
* `latency_ms`
* `error`
* `created_at`

---

# Estados de un run

Un run puede pasar por estos estados:

```text
queued
running
succeeded
failed
```

En la implementación actual, un run recién creado nace en `queued`.

Importante: `status = succeeded` significa que la ejecución técnica del run ha concluido correctamente. El resultado analítico real de la hipótesis se expresa mediante:

* `verification_summary`
* `run_memory.verification_status`
* `episode.verification_status`
* `episode.success`
* `failure_modes`

Es perfectamente válido que un run termine en `succeeded` y, al mismo tiempo, su hipótesis principal quede `refuted`.

---

# Endpoints

## 1) Listar agentes

```http
GET /api/agents/agents/
```

### Response

```json
[
  {
    "id": 1,
    "name": "geo-agent",
    "system_prompt": "",
    "is_active": true,
    "tool_allowlist": [
      "spatial.query_layer",
      "spatial.intersects",
      "spatial.nearby",
      "spatial.context_pack",
      "spatial.network_trace"
    ],
    "profile": "investigate",
    "created_at": "2026-03-20T12:00:00+01:00"
  }
]
```

---

## 2) Obtener un agente

```http
GET /api/agents/agents/{id}/
```

### Response

```json
{
  "id": 1,
  "name": "geo-agent",
  "system_prompt": "",
  "is_active": true,
  "tool_allowlist": [
    "spatial.query_layer",
    "spatial.intersects",
    "spatial.nearby",
    "spatial.context_pack",
    "spatial.network_trace"
  ],
  "profile": "rich",
  "created_at": "2026-03-20T12:00:00+01:00"
}
```

---

## 3) Crear un run

Crea el registro de ejecución. No ejecuta todavía el agente.

```http
POST /api/agents/runs/
```

### Request

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Comprueba si existe una ruta de red válida entre dos puntos",
    "map_context": {
      "bbox": {
        "west": -6.06,
        "south": 37.32,
        "east": -6.05,
        "north": 37.33
      },
      "zoom": 18
    },
    "trace_context": {
      "start_point": {
        "lon": -6.06,
        "lat": 37.3201
      },
      "end_point": {
        "lon": -6.051,
        "lat": 37.3299
      }
    }
  }
}
```

### Response

```json
{
  "id": 42,
  "agent": 1,
  "agent_name": "geo-agent",
  "user": 7,
  "status": "queued",
  "input_json": {
    "goal": "Comprueba si existe una ruta de red válida entre dos puntos",
    "map_context": {
      "bbox": {
        "west": -6.06,
        "south": 37.32,
        "east": -6.05,
        "north": 37.33
      },
      "zoom": 18
    },
    "trace_context": {
      "start_point": {
        "lon": -6.06,
        "lat": 37.3201
      },
      "end_point": {
        "lon": -6.051,
        "lat": 37.3299
      }
    }
  },
  "output_json": {},
  "final_text": "",
  "error": "",
  "verification_summary": {
    "verified": [],
    "refuted": [],
    "inconclusive": [],
    "not_evaluated": [],
    "counts": {
      "verified": 0,
      "refuted": 0,
      "inconclusive": 0,
      "not_evaluated": 0
    }
  },
  "replan_count": 0,
  "plan_history": [],
  "executed_outputs": [],
  "run_memory": null,
  "episode": null,
  "created_at": "2026-03-20T13:00:00+01:00",
  "started_at": null,
  "ended_at": null
}
```

---

## 4) Listar runs del usuario autenticado

```http
GET /api/agents/runs/
```

Este endpoint devuelve únicamente los runs del usuario autenticado.

También soporta filtros de memoria persistida. Los más útiles son:

* `verification_status`
* `domain`
* `tool`
* `layer`
* `analysis_type`

Ejemplos:

```http
GET /api/agents/runs/?verification_status=refuted
GET /api/agents/runs/?tool=spatial.network_trace
GET /api/agents/runs/?domain=network
GET /api/agents/runs/?analysis_type=network_trace
GET /api/agents/runs/?layer=demo_lines
```

### Response

```json
[
  {
    "id": 42,
    "agent": 1,
    "agent_name": "geo-agent",
    "user": 7,
    "status": "succeeded",
    "input_json": {
      "goal": "Comprueba si existe una ruta de red válida entre dos puntos"
    },
    "output_json": {
      "ok": true
    },
    "final_text": "Se encontró una ruta válida.",
    "error": "",
    "verification_summary": {
      "verified": [
        {
          "id": "s1",
          "tool": "spatial.network_trace",
          "hypothesis": "Existe una ruta de red válida entre ambos puntos",
          "target": "Comprobar si path_found es true",
          "reason": "Evaluated equals on path 'data.path_found'.",
          "observed": true,
          "criteria": {
            "path": "data.path_found",
            "equals": true
          },
          "ok": true,
          "error": ""
        }
      ],
      "refuted": [],
      "inconclusive": [],
      "not_evaluated": [],
      "counts": {
        "verified": 1,
        "refuted": 0,
        "inconclusive": 0,
        "not_evaluated": 0
      }
    },
    "replan_count": 0,
    "plan_history": [],
    "executed_outputs": [],
    "run_memory": {
      "normalized_goal": "comprueba si existe una ruta de red válida entre dos puntos",
      "goal_signature": "comprueba|ruta|red|valida|puntos",
      "domain": "network",
      "analysis_types": [
        "network_trace",
        "verification_driven"
      ],
      "layers": [
        "demo_lines"
      ],
      "tools_used": [
        "spatial.network_trace"
      ],
      "tool_sequence_signature": "spatial.network_trace",
      "verification_status": "verified",
      "failure_modes": []
    },
    "episode": {
      "domain": "network",
      "tools_used": [
        "spatial.network_trace"
      ],
      "tool_sequence": [
        "spatial.network_trace"
      ],
      "verification_status": "verified",
      "success": true,
      "failure_mode": "",
      "failure_modes": []
    },
    "created_at": "2026-03-20T13:00:00+01:00",
    "started_at": "2026-03-20T13:00:01+01:00",
    "ended_at": "2026-03-20T13:00:02+01:00"
  }
]
```

---

## 5) Obtener un run

```http
GET /api/agents/runs/{id}/
```

Devuelve el run serializado con resultado final, verificaciones, planes, outputs ejecutados, memoria persistida y episodio derivado.

### Response

```json
{
  "id": 42,
  "agent": 1,
  "agent_name": "geo-agent",
  "user": 7,
  "status": "succeeded",
  "input_json": {
    "goal": "Comprueba si existe una ruta de red válida entre dos puntos"
  },
  "output_json": {
    "ok": true,
    "goal": "Comprueba si existe una ruta de red válida entre dos puntos",
    "plan": {
      "steps": [
        {
          "id": "s1",
          "type": "tool",
          "name": "spatial.network_trace"
        },
        {
          "type": "final"
        }
      ]
    }
  },
  "final_text": "Se encontró una ruta válida.",
  "error": "",
  "verification_summary": {
    "verified": [
      {
        "id": "s1",
        "tool": "spatial.network_trace",
        "hypothesis": "Existe una ruta de red válida entre ambos puntos",
        "target": "Comprobar si path_found es true",
        "reason": "Evaluated equals on path 'data.path_found'.",
        "observed": true,
        "criteria": {
          "path": "data.path_found",
          "equals": true
        },
        "ok": true,
        "error": ""
      }
    ],
    "refuted": [],
    "inconclusive": [],
    "not_evaluated": [],
    "counts": {
      "verified": 1,
      "refuted": 0,
      "inconclusive": 0,
      "not_evaluated": 0
    }
  },
  "replan_count": 0,
  "plan_history": [
    {
      "label": "initial",
      "steps": [
        {
          "id": "s1",
          "type": "tool",
          "name": "spatial.network_trace"
        },
        {
          "type": "final"
        }
      ]
    }
  ],
  "executed_outputs": [
    {
      "id": "s1",
      "type": "tool",
      "name": "spatial.network_trace",
      "ok": true,
      "error": "",
      "attempt_count": 1,
      "latency_ms": 10,
      "latency_ms_total": 10,
      "verification": {
        "status": "verified",
        "observed": true,
        "reason": "Evaluated equals on path 'data.path_found'."
      }
    }
  ],
  "run_memory": {
    "normalized_goal": "comprueba si existe una ruta de red válida entre dos puntos",
    "goal_signature": "comprueba|ruta|red|valida|puntos",
    "domain": "network",
    "analysis_types": [
      "network_trace",
      "verification_driven"
    ],
    "layers": [
      "demo_lines"
    ],
    "tools_used": [
      "spatial.network_trace"
    ],
    "tool_sequence_signature": "spatial.network_trace",
    "final_plan": {
      "steps": [
        {
          "id": "s1",
          "type": "tool",
          "name": "spatial.network_trace"
        },
        {
          "type": "final"
        }
      ]
    },
    "plan_history": [
      {
        "label": "initial",
        "steps": [
          {
            "id": "s1",
            "type": "tool",
            "name": "spatial.network_trace"
          },
          {
            "type": "final"
          }
        ]
      }
    ],
    "structured_results": {
      "tool_count": 1,
      "successful_tools": 1,
      "failed_tools": 0
    },
    "verification_summary": {
      "counts": {
        "verified": 1,
        "refuted": 0,
        "inconclusive": 0,
        "not_evaluated": 0
      }
    },
    "verification_status": "verified",
    "outcome": {
      "status": "succeeded",
      "ok": true,
      "replan_count": 0,
      "tool_steps_executed": 1
    },
    "errors": [],
    "failure_modes": [],
    "replans": []
  },
  "episode": {
    "normalized_goal": "comprueba si existe una ruta de red válida entre dos puntos",
    "goal_signature": "comprueba|ruta|red|valida|puntos",
    "domain": "network",
    "analysis_types": [
      "network_trace",
      "verification_driven"
    ],
    "tools_used": [
      "spatial.network_trace"
    ],
    "tool_sequence": [
      "spatial.network_trace"
    ],
    "tool_sequence_signature": "spatial.network_trace",
    "outcome_status": "succeeded",
    "verification_status": "verified",
    "success": true,
    "failure_mode": "",
    "failure_modes": [],
    "recommended_strategy": "Secuencia efectiva detectada: spatial.network_trace. Próximo arranque recomendado: spatial.network_trace."
  },
  "created_at": "2026-03-20T13:00:00+01:00",
  "started_at": "2026-03-20T13:00:01+01:00",
  "ended_at": "2026-03-20T13:00:02+01:00"
}
```

---

## 6) Ejecutar un run

Lanza la ejecución del run ya creado.

```http
POST /api/agents/runs/{id}/execute/
```

### Response

Devuelve el mismo serializer enriquecido del run, ya actualizado tras la ejecución.

Ejemplo resumido de caso verificado:

```json
{
  "id": 42,
  "agent": 1,
  "agent_name": "geo-agent",
  "user": 7,
  "status": "succeeded",
  "output_json": {
    "ok": true,
    "goal": "Comprueba si existe una ruta de red válida entre dos puntos",
    "plan": {
      "steps": [
        {
          "id": "s1",
          "type": "tool",
          "name": "spatial.network_trace",
          "args": {
            "layer": "demo_lines",
            "start_point": {
              "lon": -6.055,
              "lat": 37.325
            },
            "end_point": {
              "lon": -6.056,
              "lat": 37.326
            }
          },
          "required": true,
          "success_criteria": {
            "path": "data.path_found",
            "equals": true
          }
        },
        {
          "type": "final"
        }
      ]
    },
    "final_text": "Se encontró una ruta válida.",
    "plan_history": [
      {
        "label": "initial",
        "steps": [
          {
            "id": "s1",
            "type": "tool",
            "name": "spatial.network_trace"
          },
          {
            "type": "final"
          }
        ]
      }
    ],
    "replan_count": 0,
    "executed_outputs": [
      {
        "id": "s1",
        "type": "tool",
        "name": "spatial.network_trace",
        "ok": true,
        "data": {
          "path_found": true
        },
        "error": "",
        "required": true,
        "depends_on": [],
        "attempt_count": 1,
        "latency_ms": 10,
        "latency_ms_total": 10,
        "resolved_args": {
          "layer": "demo_lines",
          "start_point": {
            "lon": -6.055,
            "lat": 37.325
          },
          "end_point": {
            "lon": -6.056,
            "lat": 37.326
          }
        },
        "success_criteria": {
          "path": "data.path_found",
          "equals": true
        },
        "verification": {
          "status": "verified",
          "target": "Comprobar si path_found es true",
          "criteria": {
            "path": "data.path_found",
            "equals": true
          },
          "observed": true,
          "reason": "Evaluated equals on path 'data.path_found'."
        }
      }
    ],
    "verification_summary": {
      "verified": [
        {
          "id": "s1",
          "tool": "spatial.network_trace",
          "observed": true
        }
      ],
      "refuted": [],
      "inconclusive": [],
      "not_evaluated": [],
      "counts": {
        "verified": 1,
        "refuted": 0,
        "inconclusive": 0,
        "not_evaluated": 0
      }
    }
  },
  "final_text": "Se encontró una ruta válida.",
  "verification_summary": {
    "verified": [
      {
        "id": "s1",
        "tool": "spatial.network_trace",
        "observed": true
      }
    ],
    "refuted": [],
    "inconclusive": [],
    "not_evaluated": [],
    "counts": {
      "verified": 1,
      "refuted": 0,
      "inconclusive": 0,
      "not_evaluated": 0
    }
  },
  "replan_count": 0,
  "run_memory": {
    "verification_status": "verified",
    "tools_used": [
      "spatial.network_trace"
    ]
  },
  "episode": {
    "verification_status": "verified",
    "success": true
  }
}
```

Ejemplo resumido de caso refutado con replan registrado:

```json
{
  "id": 99,
  "agent": 1,
  "agent_name": "geo-agent",
  "user": 7,
  "status": "succeeded",
  "output_json": {
    "ok": true,
    "goal": "Traza una ruta de red entre dos puntos desconectados",
    "replan_count": 1,
    "executed_outputs": [
      {
        "id": "s1",
        "type": "tool",
        "name": "spatial.network_trace",
        "ok": true,
        "data": {
          "path_found": false,
          "reason": "snap_distance_exceeded",
          "start_snap_m": 109.40,
          "end_snap_m": 417.54
        },
        "verification": {
          "status": "refuted",
          "target": "Comprobar si path_found es true",
          "criteria": {
            "path": "data.path_found",
            "equals": true
          },
          "observed": false,
          "reason": "Evaluated equals on path 'data.path_found'."
        }
      }
    ],
    "verification_summary": {
      "verified": [],
      "refuted": [
        {
          "id": "s1",
          "tool": "spatial.network_trace",
          "observed": false
        }
      ],
      "inconclusive": [],
      "not_evaluated": [],
      "counts": {
        "verified": 0,
        "refuted": 1,
        "inconclusive": 0,
        "not_evaluated": 0
      }
    }
  },
  "run_memory": {
    "verification_status": "refuted",
    "failure_modes": [
      "verification_refuted"
    ],
    "replans": [
      {
        "label": "replan_1"
      }
    ]
  },
  "episode": {
    "verification_status": "refuted",
    "success": false,
    "failure_mode": "verification_refuted",
    "failure_modes": [
      "verification_refuted"
    ],
    "replan_count": 1
  }
}
```

---

## 7) Obtener pasos persistidos de un run

```http
GET /api/agents/runs/{id}/steps/
```

Devuelve los `RunStep` guardados en base de datos.

### Response

```json
[
  {
    "id": 1,
    "run": 42,
    "idx": 1,
    "kind": "system",
    "name": "run.start",
    "input_json": {
      "agent_id": 1,
      "user_id": 7
    },
    "output_json": {
      "status": "running"
    },
    "latency_ms": 0,
    "error": "",
    "created_at": "2026-03-20T13:00:01+01:00"
  },
  {
    "id": 2,
    "run": 42,
    "idx": 2,
    "kind": "llm",
    "name": "llm.plan",
    "input_json": {
      "goal": "Comprueba si existe una ruta de red válida entre dos puntos",
      "execution_context": {}
    },
    "output_json": {
      "steps": [
        {
          "id": "s1",
          "type": "tool",
          "name": "spatial.network_trace"
        },
        {
          "type": "final"
        }
      ]
    },
    "latency_ms": 0,
    "error": "",
    "created_at": "2026-03-20T13:00:01+01:00"
  }
]
```

---

## 8) Obtener trace completo de un run

```http
GET /api/agents/runs/{id}/trace/
```

Este endpoint es el más útil para debugging, observabilidad e integración avanzada.

Incluye:

* metadatos del run
* steps persistidos
* trace agregado
* plan final
* historial de replans
* outputs ejecutados
* resumen de verificaciones
* métricas agregadas
* memoria persistida del run
* episodio derivado

### Response

```json
{
  "id": 42,
  "agent": 1,
  "agent_name": "geo-agent",
  "user": 7,
  "status": "succeeded",
  "input_json": {
    "goal": "ejecución completa API"
  },
  "output_json": {
    "ok": true
  },
  "final_text": "síntesis desde API",
  "error": "",
  "created_at": "2026-03-20T13:48:27.355458+01:00",
  "started_at": "2026-03-20T13:48:27.358430+01:00",
  "ended_at": "2026-03-20T13:48:27.364528+01:00",
  "steps": [
    {
      "id": 1,
      "run": 42,
      "idx": 1,
      "kind": "system",
      "name": "run.start",
      "input_json": {
        "agent_id": 1,
        "user_id": 7
      },
      "output_json": {
        "status": "running"
      },
      "latency_ms": 0,
      "error": "",
      "created_at": "2026-03-20T13:48:27.360085+01:00"
    }
  ],
  "trace": {
    "goal": "ejecución completa API",
    "plan": {
      "steps": [
        {
          "id": "s1",
          "type": "tool",
          "name": "spatial.network_trace"
        },
        {
          "type": "final"
        }
      ]
    },
    "plan_history": [
      {
        "label": "initial",
        "steps": [
          {
            "id": "s1",
            "type": "tool",
            "name": "spatial.network_trace"
          },
          {
            "type": "final"
          }
        ]
      }
    ],
    "replan_count": 0,
    "executed_outputs": [
      {
        "id": "s1",
        "type": "tool",
        "name": "spatial.network_trace",
        "ok": true,
        "error": "",
        "attempt_count": 1,
        "latency_ms": 10,
        "latency_ms_total": 10,
        "verification": {
          "status": "verified",
          "observed": true,
          "reason": "Evaluated equals on path 'data.path_found'."
        }
      }
    ],
    "verification_summary": {
      "verified": [
        {
          "id": "s1",
          "tool": "spatial.network_trace",
          "ok": true,
          "hypothesis": "Existe una ruta de red válida entre ambos puntos",
          "target": "Comprobar si path_found es true",
          "criteria": {
            "path": "data.path_found",
            "equals": true
          },
          "observed": true,
          "reason": "Evaluated equals on path 'data.path_found'.",
          "depends_on": [],
          "resolved_args": {
            "layer": "demo_lines",
            "start_point": {
              "lon": -6.055,
              "lat": 37.325
            },
            "end_point": {
              "lon": -6.056,
              "lat": 37.326
            }
          },
          "attempt_count": 1,
          "error": ""
        }
      ],
      "refuted": [],
      "inconclusive": [],
      "not_evaluated": [],
      "counts": {
        "verified": 1,
        "refuted": 0,
        "inconclusive": 0,
        "not_evaluated": 0
      }
    },
    "stats": {
      "tool_steps_executed": 1,
      "total_attempts": 1,
      "total_latency_ms": 10,
      "persisted_steps": 5
    }
  },
  "run_memory": {
    "verification_status": "verified",
    "tools_used": [
      "spatial.network_trace"
    ]
  },
  "episode": {
    "verification_status": "verified",
    "success": true
  }
}
```

---

# Modelo de entrada habitual

La API no impone un shape único más allá de `input_json`, pero el caso típico es:

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Traza una ruta por la red",
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
}
```

Para network trace, el shape recomendable es:

```json
{
  "agent": 1,
  "input_json": {
    "goal": "Traza una ruta de red entre dos puntos",
    "map_context": {
      "bbox": {
        "west": -6.06,
        "south": 37.32,
        "east": -6.05,
        "north": 37.33
      },
      "zoom": 18
    },
    "trace_context": {
      "start_point": {
        "lon": -6.06,
        "lat": 37.3201
      },
      "end_point": {
        "lon": -6.051,
        "lat": 37.3299
      }
    }
  }
}
```

También puede usarse un `tool_call` directo dentro de `input_json` si el runner lo soporta para ejecución directa de una tool:

```json
{
  "agent": 1,
  "input_json": {
    "goal": "forzar trace refutado",
    "tool_call": {
      "name": "spatial.network_trace",
      "args": {
        "layer": "demo_lines",
        "start_point": {
          "lon": -6.06,
          "lat": 37.3201
        },
        "end_point": {
          "lon": -6.051,
          "lat": 37.3299
        },
        "bbox": {
          "west": -6.06,
          "south": 37.32,
          "east": -6.05,
          "north": 37.33
        },
        "include_geom": true,
        "max_snap_distance_m": 20
      }
    }
  }
}
```

---

# Semántica del trace

## plan

Contiene el plan finalmente ejecutado.

## plan_history

Guarda el historial de planes, incluyendo el inicial y los posibles replans.

## executed_outputs

Lista de pasos tool ejecutados con:

* `id`
* `name`
* `resolved_args`
* `ok`
* `data`
* `error`
* `attempts`
* `attempt_count`
* `latency_ms`
* `latency_ms_total`
* `verification`

## verification_summary

Agrupa los resultados por estado:

* `verified`
* `refuted`
* `inconclusive`
* `not_evaluated`

e incluye un bloque `counts`.

## run_memory

Memoria operacional persistida del run. Resume la ejecución en una estructura útil para filtrado, recuperación y analítica.

Campos habituales:

* `normalized_goal`
* `goal_signature`
* `domain`
* `analysis_types`
* `layers`
* `tools_used`
* `tool_sequence_signature`
* `final_plan`
* `plan_history`
* `structured_results`
* `verification_summary`
* `verification_status`
* `outcome`
* `errors`
* `failure_modes`
* `replans`

## episode

Memoria episódica derivada de la ejecución. Resume el patrón de resolución del agente y el resultado final de la hipótesis.

Campos habituales:

* `normalized_goal`
* `goal_signature`
* `domain`
* `analysis_types`
* `tools_used`
* `tool_sequence`
* `tool_sequence_signature`
* `outcome_status`
* `verification_status`
* `success`
* `failure_mode`
* `failure_modes`
* `recommended_strategy`
* `verification_summary`
* `evidence`
* `replan_count`

## stats

Métricas agregadas del run:

* `tool_steps_executed`
* `total_attempts`
* `total_latency_ms`
* `persisted_steps`

---

# Aislamiento por usuario

El recurso `runs` está filtrado por usuario autenticado, por lo que cada usuario solo puede listar y acceder a sus propios runs.

Las operaciones sobre runs ajenos deben responder `404`.

---

# Ejemplo de integración en JavaScript

```javascript
const createRes = await fetch("/api/agents/runs/", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Token TU_TOKEN"
  },
  body: JSON.stringify({
    agent: 1,
    input_json: {
      goal: "Traza una ruta por la red",
      map_context: {
        bbox: {
          west: -6.06,
          south: 37.32,
          east: -6.05,
          north: 37.33
        },
        zoom: 18
      }
    }
  })
});

const run = await createRes.json();

await fetch(`/api/agents/runs/${run.id}/execute/`, {
  method: "POST",
  headers: {
    "Authorization": "Token TU_TOKEN"
  }
});

const traceRes = await fetch(`/api/agents/runs/${run.id}/trace/`, {
  headers: {
    "Authorization": "Token TU_TOKEN"
  }
});

const trace = await traceRes.json();
console.log(trace);
```

---

# Ejemplo de integración en Python

```python
import requests

BASE = "http://localhost:8000/api/agents"
TOKEN = "TU_TOKEN"

headers = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
}

create_resp = requests.post(
    f"{BASE}/runs/",
    headers=headers,
    json={
        "agent": 1,
        "input_json": {
            "goal": "Traza una ruta por la red",
            "map_context": {
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33,
                },
                "zoom": 18,
            },
        },
    },
)
create_resp.raise_for_status()
run = create_resp.json()

execute_resp = requests.post(
    f"{BASE}/runs/{run['id']}/execute/",
    headers={"Authorization": f"Token {TOKEN}"},
)
execute_resp.raise_for_status()

trace_resp = requests.get(
    f"{BASE}/runs/{run['id']}/trace/",
    headers={"Authorization": f"Token {TOKEN}"},
)
trace_resp.raise_for_status()

print(trace_resp.json())
```

---

# Buenas prácticas

* enviar `map_context.bbox` cuando el análisis sea espacial
* enviar `zoom` si está disponible
* para trazados de red, enviar también `trace_context.start_point` y `trace_context.end_point`
* no asumir que crear un run implica ejecutarlo
* usar `trace` para debugging y observabilidad
* usar `steps` cuando se quiera inspeccionar el log persistido
* apoyarse en `verification_summary` para evaluar si una hipótesis quedó confirmada o refutada
* apoyarse en `run_memory` y `episode` para recuperación, analítica y ranking de estrategias
* tratar `final_text` como síntesis final, no como sustituto del detalle técnico del trace

---

# Errores esperables

## 400 Bad Request

Payload inválido o datos insuficientes.

## 401 Unauthorized / 403 Forbidden

Autenticación ausente o no válida.

## 404 Not Found

Run inexistente o perteneciente a otro usuario.

## 500 / failed run

Error interno durante planificación, ejecución de tools o síntesis. En esos casos, el run puede quedar con:

```json
{
  "status": "failed",
  "error": "mensaje de error"
}
```

---

# Resumen

La API de GeoAgents no solo expone agentes y ejecuciones, sino también memoria persistente de comportamiento del agente. Esto permite:

* ejecutar y auditar runs
* inspeccionar planes y replans
* verificar hipótesis con trazabilidad
* recuperar ejecuciones pasadas por criterios semánticos
* analizar estrategias exitosas y fallidas
* construir observabilidad real sobre agentes GIS y no GIS
