Cada caso dispara la tool correcta:

* `intersects_simple` → `spatial.intersects`
* `nearby_simple` → `spatial.nearby`
* `summary_simple` → `spatial.context_pack`
* `query_points_layer` / `query_polygons_layer` → `spatial.query_layer`

Eso significa que ya tienes una **capa de routing semántico** bastante sólida.

### 2. La inferencia GIS funciona

Especialmente importante:

* `spatial.intersects` se resuelve bien
* `spatial.nearby` se resuelve bien
* `spatial.query_layer` entra correctamente en puntos y polígonos

Eso ya convierte a GeoAgents en algo bastante más autónomo.

### 3. Los perfiles ya afectan al plan

El caso más representativo es:

* `mixed_context_intersects`

  * `compact` → `spatial.intersects`
  * `rich` / `investigate` → `spatial.intersects` + `spatial.context_pack`

Eso ya es una diferencia real de estrategia, no solo de redacción.

---

# Lectura honesta

El sistema está ya en una fase donde el núcleo funcional existe.
A partir de aquí, el valor vendrá más de:

* robustez
* precisión semántica
* enriquecimiento de análisis

que de añadir tools básicas nuevas.

---

# Siguiente paso recomendado

## **Refinar el synthesizer con templates/facts por tool**

Ahora mismo la tool selection está bastante bien.
Lo que más retorno te va a dar ahora es que la salida final sea:

* más controlada
* más consistente
* menos dependiente del estilo del modelo

### Objetivo

Que el texto final no sea solo “LLM libre”, sino una síntesis más guiada por facts estructurados.

---

# Qué haría exactamente

## Paso 1

Enriquecer `build_tool_facts()` para cada tool:

### `spatial.query_layer`

Añadir facts como:

* capa consultada
* número total de elementos
* nombres de los primeros elementos
* tipos geométricos predominantes

### `spatial.nearby`

Añadir:

* nº de elementos encontrados
* elemento más cercano
* distancia mínima
* capa consultada

### `spatial.context_pack`

Añadir:

* capa dominante
* nº de capas no vacías
* nº total de features
* highlights limpios

### `spatial.intersects`

Añadir:

* pares únicos intersectados
* count_total
* geometría de intersección
* sin inferencias topológicas extra

---

## Paso 2

Hacer que el synthesizer use micro-reglas por tool:

* si solo hay `context_pack`, no hablar de topología
* si hay `intersects`, usar “se detectó intersección entre…”
* si hay `nearby`, hablar de proximidad y distancias
* si hay `query_layer`, hablar de inventario/consulta de capa

---

## Paso 3

Opcionalmente, crear un `response_profile` más marcado:

* `compact` → 1 párrafo + 3 hallazgos máximo
* `rich` → estructura completa
* `investigate` → estructura completa + observaciones y límites

---

# Alternativa si quieres algo más de framework

Si prefieres seguir por arquitectura en vez de calidad de respuesta, el siguiente paso sería:

## **Run memory / context chaining**

Permitir que un run pueda reutilizar resultados previos:

* “ahora analiza solo la capa de puntos”
* “después mira qué hay cerca de A”
* “usa el bbox anterior”

Pero yo no iría aún ahí. Primero dejaría la síntesis muy fina.

---

# Mi recomendación exacta

Procedería con:

## **Paso siguiente: refinar `synthesizer.py` y `build_tool_facts()`**

Porque:

* la selección de tool ya funciona
* la inferencia GIS ya funciona
* ahora toca que el resultado final se sienta realmente profesional y estable

Si quieres, en el siguiente mensaje te dejo una versión mejorada de `synthesizer.py` con facts más ricos para:

* `spatial.query_layer`
* `spatial.nearby`
* `spatial.context_pack`
* `spatial.intersects`
