# GeoAgents Examples

Este directorio contiene ejemplos reproducibles oficiales de Fase 1.5.

## 01_simple_layer_query.json

Caso canónico de consulta simple de capa.

Objetivo:
- validar el flujo mínimo de `query_layer`
- comprobar serialización del run
- obtener un `trace` limpio sin replan

## 02_multi_tool_with_references.json

Caso canónico de workflow multi-tool con referencias entre pasos.

Objetivo:
- validar razonamiento multi-step
- comprobar resolución de referencias `$step:...`
- verificar reutilización de outputs previos

## 03_refuted_hypothesis_with_replan.json

Caso canónico de hipótesis refutada con replan.

Objetivo:
- validar `success_criteria`
- comprobar estado `refuted`
- verificar replan básico del runner

## Flujo recomendado

1. Crear run con `POST /api/agents/runs/`
2. Ejecutar run con `POST /api/agents/runs/{id}/execute/`
3. Inspeccionar `GET /api/agents/runs/{id}/trace/`

## Ejemplo curl

```bash
curl -X POST http://localhost:8000/api/agents/runs/ \
  -H "Authorization: Token TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/01_simple_layer_query.json