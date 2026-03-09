# GeoAgents Usage Guide

Esta guía explica cómo:

- crear agentes
- ejecutar runs
- usar tools
- extender el framework

---

# Crear un agente

Ejemplo en Django shell:

````

python manage.py shell

````

```python
from agents_core.models import Agent

agent = Agent.objects.create(
    name="geo-agent",
    system_prompt="Eres un experto en análisis espacial.",
    profile="rich",
    tool_allowlist=[
        "spatial.intersects",
        "spatial.nearby",
        "spatial.query_layer",
        "spatial.context_pack"
    ],
)
````

---

# Ejecutar un run

Ejemplo:

```python
from agents_core.models import Run
from agents_core.runner import execute_run

run = Run.objects.create(
    agent=agent,
    input_json={
        "goal": "Comprueba si los puntos están dentro de las zonas",
        "map_context": {
            "bbox": {...},
            "zoom": 18
        }
    }
)

execute_run(run)
```

---

# Resultado

Después de ejecutar:

```
run.final_text
```

contendrá la respuesta del agente.

---

# Ejecutar tests

El proyecto incluye `test.py`.

Ejecutar:

```
python test.py
```

El script prueba múltiples escenarios:

```
intersects
nearby
query_layer
context_pack
```

y compara perfiles.

---

# Extender el sistema

Para añadir nueva funcionalidad:

### nueva tool

```
agents_gis/tools
```

### nuevas heurísticas

```
plan_postprocessor.py
```

### nuevas inferencias

```
agents_gis/inference.py
```

---

# Buenas prácticas

1️⃣ limitar tools por agente

2️⃣ usar postprocessor para completar args

3️⃣ mantener tools deterministas

4️⃣ usar facts estructurados

---

# Roadmap

Futuras mejoras posibles:

* soporte raster
* reasoning multi-step
* memoria de runs
* análisis 3D
* routing espacial

