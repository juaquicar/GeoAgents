# GeoAgents Agents

Un agente es una configuración del sistema que define:

- herramientas permitidas
- prompt del sistema
- perfil de comportamiento
- límites operativos del razonamiento del agente

En GeoAgents, un `Agent` no ejecuta tools por sí mismo ni contiene memoria propia. Su función es definir el marco dentro del cual el runner puede planificar y ejecutar un `Run`.

---

# Modelo Agent

Campos principales:

```text
name
system_prompt
profile
tool_allowlist
is_active
````

Significado práctico de cada campo:

* `name`: nombre funcional del agente.
* `system_prompt`: instrucciones base del comportamiento del agente.
* `profile`: profundidad o agresividad del razonamiento.
* `tool_allowlist`: lista cerrada de tools autorizadas para ese agente.
* `is_active`: habilita o deshabilita el uso del agente.

---

# Profiles

GeoAgents soporta tres perfiles base.

---

## compact

Modo mínimo.

Objetivo:

resolver la consulta con la menor cantidad posible de tools y con el menor coste de ejecución razonable.

Ejemplo:

```text
intersects -> solo intersects
```

Cuándo usarlo:

* consultas sencillas
* contextos donde importa la latencia
* integraciones ligeras
* respuestas rápidas en visor o API

---

## rich

Modo enriquecido.

Objetivo:

resolver la consulta con algo más de contexto y trazabilidad, evitando redundancia.

Ejemplo:

```text
intersects + context_pack
```

Cuándo usarlo:

* respuestas explicativas
* casos de uso generales GIS
* análisis para usuario final
* situaciones donde interesa combinar resultado y contexto

---

## investigate

Modo exploratorio.

Objetivo:

permitir análisis más profundo, multi-step y con mayor capacidad de contraste o verificación.

Ejemplo:

```text
query_layer
nearby
intersects
```

También puede incluir workflows como:

```text
query_layer -> nearby -> network_trace
```

Cuándo usarlo:

* debugging
* análisis complejos
* inspección técnica
* workflows en los que importa el detalle del razonamiento

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
    "spatial.context_pack",
    "spatial.network_trace",
]
```

Esto evita que el LLM invoque herramientas no permitidas y convierte la selección de tools en una capacidad gobernada por configuración.

La `tool_allowlist` cumple varias funciones:

* seguridad
* control de dominio
* reducción de errores del planner
* reproducibilidad
* especialización por agente

---

# Ejemplo de agente

```python
from agents_core.models import Agent

Agent.objects.create(
    name="GIS Agent",
    system_prompt="Eres un agente experto en análisis geoespacial",
    profile="rich",
    tool_allowlist=[
        "spatial.intersects",
        "spatial.nearby",
        "spatial.query_layer",
        "spatial.context_pack",
        "spatial.network_trace",
    ],
)
```

---

# Responsabilidad real de un Agent

Un `Agent` en GeoAgents no es una entidad autónoma completa. Su responsabilidad real es:

* acotar el espacio de decisión del planner
* definir el estilo de razonamiento
* controlar qué tools pueden entrar en el plan
* modular la profundidad del análisis
* condicionar indirectamente la normalización del plan

La ejecución real pertenece al runner.

---

# Fase 1: Agente de verdad

GeoAgents incorpora capacidades para un ciclo de ejecución más robusto y trazable.

## Multi-tool reasoning

El planificador puede proponer múltiples tools con orden explícito.

Esto permite construir workflows como:

* explorar una capa
* reutilizar el resultado en un paso posterior
* verificar una hipótesis
* sintetizar la respuesta final

Ejemplo conceptual:

```text
query_layer -> nearby -> final
```

## Hipótesis verificables

Cada paso de tipo tool puede incluir:

* `hypothesis`
* `verification_target`
* `success_criteria`

Esto convierte cada step en una unidad no solo ejecutable, sino también evaluable.

Ejemplo:

```json
{
  "id": "s1",
  "type": "tool",
  "name": "spatial.network_trace",
  "hypothesis": "Existe una ruta de red válida entre los puntos",
  "verification_target": "Confirmar si path_found es true",
  "success_criteria": {
    "path": "data.path_found",
    "equals": true
  }
}
```

## Referencias entre pasos

Los argumentos aceptan referencias del tipo:

```text
$step:s1.data.features.0.centroid
```

Esto permite que un paso posterior consuma directamente el output de un paso anterior.

## Control de ejecución

Cada paso puede definir:

* `depends_on`
* `on_fail`
* `required`
* `timeout_s`
* `max_retries`
* `retry_backoff_s`
* `can_replan`

Esto permite que el agente no sea una simple secuencia ciega de tools, sino un flujo controlado y observable.

---

# Ejemplo de step multi-tool

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

---

# Qué significa hoy “agente de verdad” en GeoAgents

En el estado actual del framework, un agente ya puede:

* planificar varios pasos
* encadenar tools
* reutilizar outputs previos
* verificar hipótesis
* registrar intentos y tiempos
* replanificar de forma básica
* producir una síntesis final basada en evidencias

El ciclo lógico del agente es:

```text
plan -> execute -> verify -> optional replan -> synthesize
```

---

# Qué no resuelve todavía el Agent

Aunque Fase 1.5 deja el agente bien consolidado, todavía no implica:

* memoria persistente entre runs
* aprendizaje estable entre episodios
* heurísticas reutilizables avanzadas
* paralelización de ramas
* selección adaptativa basada en histórico

Eso pertenece a fases posteriores del roadmap.

---

# Buenas prácticas para definir agentes

* mantener `tool_allowlist` lo más cerrada posible
* usar `compact` cuando la latencia o coste importe mucho
* usar `rich` como perfil general por defecto
* usar `investigate` para agentes de análisis técnico
* no mezclar tools irrelevantes de distintos dominios en una misma allowlist
* tratar el `system_prompt` como guía de decisión, no como sustituto de validación

---

# Recomendaciones por tipo de agente

## Agente de visor GIS

Perfil sugerido:

```text
rich
```

Tools sugeridas:

* `spatial.query_layer`
* `spatial.nearby`
* `spatial.intersects`
* `spatial.context_pack`

## Agente de red

Perfil sugerido:

```text
investigate
```

Tools sugeridas:

* `spatial.query_layer`
* `spatial.network_trace`
* `spatial.intersects`

## Agente de inspección rápida

Perfil sugerido:

```text
compact
```

Tools sugeridas:

* una o dos tools especializadas
* evitar pipelines largos



