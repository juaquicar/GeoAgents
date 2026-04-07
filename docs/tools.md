# GeoAgents Tools

Las tools son las **acciones que el agente puede ejecutar**.

Cada tool:

* recibe parámetros
* ejecuta lógica GIS
* devuelve resultados estructurados
* puede alimentar verificaciones
* aporta evidencia para la síntesis final

En GeoAgents, las tools no se invocan libremente por texto. Se invocan a través de:

* planner
* validación de plan
* runner
* executor de tools

---

# Contrato conceptual de una tool

Una tool debería cumplir idealmente estas propiedades:

* input claro y serializable
* salida estructurada
* comportamiento razonablemente determinista
* semántica estable
* errores comprensibles
* buena integración con verificación y síntesis

---

# Herramientas actuales

## spatial.intersects

Detecta intersecciones espaciales entre capas.

### Uso

```text id="5sq9gf"
point vs polygon
line vs polygon
polygon vs polygon
```

### Input

```json id="6xx6mo"
{
  "source_layer": "demo_points",
  "target_layer": "demo_polygons",
  "bbox": {
    "west": -6.06,
    "south": 37.32,
    "east": -6.05,
    "north": 37.33
  },
  "limit": 20
}
```

### Output conceptual

```json id="d7fbas"
{
  "source_layer": "demo_points",
  "target_layer": "demo_polygons",
  "count_total": 1,
  "items": [
    {
      "source_name": "A",
      "target_name": "Zona 1",
      "intersection_geom_type": "POINT"
    }
  ]
}
```

### Cuándo usarla

* detectar cruce o solape entre capas
* validar relaciones espaciales explícitas
* comprobar si existen intersecciones en un área

### Nota semántica

`spatial.intersects` demuestra intersección, no necesariamente contención.

---

## spatial.nearby

Busca elementos cercanos a un punto.

### Input

```json id="lglvrt"
{
  "layer": "demo_points",
  "point": {
    "lon": -6.05,
    "lat": 37.33
  },
  "radius_m": 250
}
```

### Output conceptual

```json id="d3jbdn"
{
  "layer": "demo_points",
  "point": {
    "lon": -6.05,
    "lat": 37.33
  },
  "count_total": 2,
  "features": [
    {
      "id": 1,
      "name": "P1",
      "distance_m": 34.5,
      "geometry_type": "Point"
    }
  ]
}
```

### Cuándo usarla

* proximidad
* análisis de entorno inmediato
* detección de activos cercanos a una posición

---

## spatial.query_layer

Consulta directa de una capa.

### Input

```json id="6wwvwr"
{
  "layer": "demo_points",
  "bbox": {
    "west": -6.06,
    "south": 37.32,
    "east": -6.05,
    "north": 37.33
  },
  "limit": 50
}
```

### Output conceptual

```json id="v9r56h"
{
  "layer": "demo_points",
  "count_total": 3,
  "features": [
    {
      "id": 1,
      "name": "P1",
      "geometry_type": "Point",
      "centroid": {
        "lon": -6.055,
        "lat": 37.325
      }
    }
  ]
}
```

### Cuándo usarla

* exploración básica de una capa
* obtención de features para alimentar otros pasos
* consultas con bbox
* workflows multi-step con referencias

---

## spatial.context_pack

Genera un resumen espacial agregado del área.

Incluye típicamente:

* capas presentes
* número de elementos
* tipos de geometría
* highlights
* resumen ejecutivo

### Cuándo usarla

* contexto espacial general
* respuestas explicativas
* primer paso cuando el goal es muy amplio

### Nota

Es útil para contexto, pero no sustituye una tool topológica específica.

---

## spatial.summary

Resumen agregado de capas dentro de un bbox.

### Uso típico

* inspección rápida del contenido espacial de una zona
* métricas básicas por capa
* recuentos y tipos geométricos

---

## spatial.network_trace

Traza una ruta o recorrido sobre una red.

### Input típico

```json id="n4hl0g"
{
  "layer": "demo_lines",
  "start_point": {
    "lon": -6.055,
    "lat": 37.325
  },
  "end_point": {
    "lon": -6.056,
    "lat": 37.326
  }
}
```

### Output conceptual

```json id="l9tq13"
{
  "path_found": true,
  "segments": [
    {
      "name": "seg-1"
    }
  ],
  "node_count": 5,
  "total_length_m": 120.5
}
```

### Cuándo usarla

* trazado de rutas sobre red
* validación de conectividad
* análisis técnico de recorridos

### Ejemplo de verificación útil

```json id="kyx3q4"
{
  "path": "data.path_found",
  "equals": true
}
```

---


## spatial.route_cost

Optimiza rutas en red con una métrica de coste configurable.

### Capacidades

* coste por longitud (`length_weight`)
* coste por tipo de segmento (`segment_type_costs` + `segment_type_field`)
* penalizaciones por segmento o por tipo (`segment_penalties`, `segment_type_penalties`)
* restricciones (`forbidden_segment_ids`, `forbidden_segment_types`, `max_segment_length_m`)
* ruta óptima según métrica (`metric = "length" | "cost"`)

### Cuándo usarla

* FTTH con jerarquías de traza
* utility networks con reglas operativas
* despliegues con segmentos preferidos/evitados
* rutas técnicas con restricciones explícitas

---

## spatial.network_service_area

Calcula alcance de servicio real sobre topología de red desde un origen.

### Capacidades

* área alcanzable desde origen (`origin_point`)
* límites por coste o distancia (`max_cost`, `max_distance_m`)
* cobertura sobre red conectada real (no buffer euclídeo)
* análisis de servicio sobre topología de red

### Cuándo usarla

* cobertura FTTH
* utility networks
* planificación de despliegue
* análisis de cobertura efectiva

---

## spatial.aggregate

Agrupa elementos de una capa por uno o más campos y calcula estadísticas por grupo.

### Capacidades

* recuento por grupo (`COUNT(*)`)
* estadísticas opcionales (`SUM`, `AVG`, `MIN`, `MAX`) sobre campos numéricos
* filtros de atributo y filtro espacial por `bbox`
* hasta 4 campos en `group_by`
* ordenación por recuento o por un agregado

### Cuándo usarla

* "¿cuántos elementos hay por tipo/categoría?"
* "¿qué tipo predomina en esta zona?"
* "suma del campo X por grupo"
* distribuciones estadísticas de una capa

### Input

```json
{
  "layer": "demo_lines",
  "group_by": ["category_n", "type_name"],
  "aggs": [
    {"field": "length_m", "func": "sum", "alias": "longitud_total"}
  ],
  "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
  "order_by": "count_desc",
  "limit": 50
}
```

### Output

```json
{
  "layer": "demo_lines",
  "group_by": ["category_n", "type_name"],
  "total_groups": 5,
  "groups": [
    {"category_n": "Fiber", "type_name": "buried", "count": 42, "longitud_total": 3820.5}
  ]
}
```

---

## spatial.buffer

Encuentra elementos de una capa (`target_layer`) dentro de un radio (`buffer_m`) alrededor de una geometría fuente.

A diferencia de `spatial.nearby` (solo punto), la fuente puede ser cualquier geometría de capa (línea, polígono…).

### Capacidades

* búsqueda dentro de radio métrico exacto (`ST_DWithin` con geography)
* fuente puntual (`source_point`) o elemento de capa (`source_layer + source_id`)
* resultados ordenados por `distance_m` ascendente
* filtros de atributo y `bbox` opcionales

### Cuándo usarla

* "elementos a X metros de este tramo/parcela/estructura"
* la fuente es una geometría no puntual (línea, polígono)
* "influencia espacial de un elemento concreto"

### Input

```json
{
  "target_layer": "demo_points",
  "buffer_m": 100,
  "source_layer": "demo_lines",
  "source_id": 5,
  "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33}
}
```

También admite fuente puntual:

```json
{
  "target_layer": "demo_points",
  "buffer_m": 50,
  "source_point": {"lon": -6.055, "lat": 37.325}
}
```

### Output

```json
{
  "target_layer": "demo_points",
  "source": {"type": "layer_element", "layer": "demo_lines", "id": 5},
  "buffer_m": 100,
  "count_total": 3,
  "items": [
    {"id": 1, "name": "A", "distance_m": 12.3, "lon": -6.054, "lat": 37.324}
  ]
}
```

---


# Tools y verificación

Desde Fase 1.5, una tool puede ejecutarse como parte de un step con:

* `hypothesis`
* `verification_target`
* `success_criteria`

Ejemplo:

```json id="jep2h1"
{
  "id": "s1",
  "type": "tool",
  "name": "spatial.network_trace",
  "hypothesis": "Existe una ruta válida entre ambos puntos",
  "verification_target": "Comprobar si path_found es true",
  "success_criteria": {
    "path": "data.path_found",
    "equals": true
  },
  "args": {
    "layer": "demo_lines",
    "start_point": {"lon": -6.055, "lat": 37.325},
    "end_point": {"lon": -6.056, "lat": 37.326}
  }
}
```

---

# Tools y referencias entre pasos

Las tools pueden consumir outputs de pasos previos mediante referencias.

Ejemplo:

```json
{
  "id": "s2",
  "type": "tool",
  "name": "spatial.nearby",
  "depends_on": ["s1"],
  "args": {
    "layer": "demo_points",
    "point": {
      "lon": "$step:s1.data.items.0.lon",
      "lat": "$step:s1.data.items.0.lat"
    },
    "radius_m": 100
  }
}
```

Nota: `spatial.query_layer` devuelve los resultados en `data.items` (no `data.features`).
Cada item incluye `lon` y `lat` como campos top-level (centroide del elemento).
Usa siempre `$step:s1.data.items.0.lon` / `.lat`, nunca `$step:s1.data.items.0.centroid`.

Esto hace posible el razonamiento multi-tool real.

---

# Buenas prácticas de diseño de tools

* devolver estructuras JSON estables
* evitar output ambiguo
* incluir campos útiles para síntesis y verificación
* no mezclar presentación con datos
* exponer nombres de capa y contadores cuando tenga sentido
* mantener comportamiento determinista siempre que sea posible
* usar mensajes de error útiles y breves

---

# Añadir una nueva tool

Pasos recomendados:

1. crear el archivo de implementación
2. implementar la función principal
3. registrar la tool en el registry
4. exponerla en introspection si aplica
5. añadir tests unitarios
6. añadir heurística o soporte del planner/postprocessor
7. añadir facts o soporte del synthesizer si hace falta
8. documentarla en este documento y en ejemplos de uso

Ruta habitual de implementación:

```text id="8e6yqj"
agents_gis/
```

Dependiendo del tipo de tool, puede vivir en archivos como:

```text id="rx6nrf"
tools_query.py
tools_nearby.py
tools_intersects.py
tools_context.py
tools_network_trace.py
```

---

# Roadmap de tools

Evoluciones naturales previstas:

* `spatial.cluster` — agrupación espacial (DBSCAN, k-means)
* `spatial.visibility` — análisis de visibilidad / cuencas visuales
* `spatial.dissolve` — unión de geometrías por campo
