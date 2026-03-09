# GeoAgents Tools

Las tools son las **acciones que el agente puede ejecutar**.

Cada tool:

- recibe parámetros
- ejecuta lógica GIS
- devuelve resultados estructurados
- genera facts para el synthesizer

---

# spatial.intersects

Detecta intersecciones espaciales entre capas.

### Uso

````

point vs polygon
line vs polygon
polygon vs polygon

````

### Input

```json
{
  "source_layer": "demo_points",
  "target_layer": "demo_polygons",
  "bbox": {...},
  "limit": 20
}
````

### Output

```json
{
  "intersections": [
    {
      "source": "A",
      "target": "Zona 1",
      "geometry": "POINT"
    }
  ]
}
```

---

# spatial.nearby

Busca elementos cercanos a un punto.

### Input

```json
{
  "layer": "demo_points",
  "point": {"lon": -6.05, "lat": 37.33},
  "radius_m": 250
}
```

### Output

```
features cercanas
distancias
```

---

# spatial.query_layer

Consulta directa de una capa.

### Input

```json
{
  "layer": "demo_points",
  "bbox": {...},
  "limit": 50
}
```

### Output

```
features
atributos
estadísticas
```

---

# spatial.context_pack

Genera un resumen espacial del área.

Incluye:

* capas presentes
* número de elementos
* tipos de geometría
* highlights

---

# Añadir una nueva tool

Pasos:

1️⃣ crear archivo en

```
agents_gis/tools/
```

2️⃣ implementar función principal

3️⃣ registrar tool

4️⃣ añadir heurística en `plan_postprocessor`

5️⃣ añadir facts para synthesizer


