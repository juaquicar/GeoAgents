# GeoAgents Agents

Un agente es una configuración del sistema que define:

- herramientas permitidas
- prompt del sistema
- perfil de comportamiento

---

# Modelo Agent

Campos principales:

````

name
system_prompt
profile
tool_allowlist
is_active

```

---

# Profiles

GeoAgents soporta tres perfiles.

---

## compact

Modo mínimo.

Objetivo:

resolver la consulta con la menor cantidad de tools.

Ejemplo:

```

intersects → solo intersects

```

---

## rich

Modo enriquecido.

Añade contexto adicional.

Ejemplo:

```

intersects + context_pack

```

---

## investigate

Modo exploratorio.

Permite análisis más profundo.

Ejemplo:

```

query_layer
nearby
intersects

````

---

# Tool allowlist

Cada agente define qué tools puede usar.

Ejemplo:

```python
[
 "spatial.summary",
 "spatial.query_layer",
 "spatial.nearby",
 "spatial.intersects",
 "spatial.context_pack"
]
````

Esto evita que el LLM invoque herramientas no permitidas.

---

# Ejemplo de agente

```python
Agent.objects.create(
    name="GIS Agent",
    system_prompt="Eres un agente experto en análisis geoespacial",
    profile="rich",
    tool_allowlist=[
        "spatial.intersects",
        "spatial.nearby",
        "spatial.query_layer",
        "spatial.context_pack"
    ],
)
```



# Fase 1: Agente de verdad

GeoAgents incorpora capacidades para un ciclo de ejecución más robusto:

- **Multi-tool reasoning**: el planificador puede proponer múltiples tools con orden explícito.
- **Hipótesis verificables**: cada paso de tool puede incluir `hypothesis` para validar lo que se espera comprobar.
- **Referencias entre pasos**: los argumentos aceptan referencias del tipo `$step:s1.data.features.0.centroid`.
- **Control de ejecución**: cada paso puede definir `depends_on` y `on_fail` (`abort` / `continue`).

Ejemplo de step:

```json
{
  "id": "s2",
  "type": "tool",
  "name": "spatial.nearby",
  "depends_on": ["s1"],
  "hypothesis": "Hay puntos cercanos al centro detectado en s1",
  "on_fail": "continue",
  "args": {
    "layer": "demo_points",
    "point": "$step:s1.data.features.0.centroid",
    "radius_m": 100
  }
}
```
