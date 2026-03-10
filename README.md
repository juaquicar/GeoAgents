# GeoAgents

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)]()
[![Django](https://img.shields.io/badge/django-4.x-green.svg)]()
[![PostGIS](https://img.shields.io/badge/postgis-enabled-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()

**GeoAgents** is an open-source framework for building **AI agents specialized in geospatial analysis (GIS)**.

It allows AI agents to:

- understand spatial questions
- select GIS tools automatically
- execute spatial analysis
- generate natural language explanations

GeoAgents is designed for:

- GIS applications
- geospatial platforms
- telecom infrastructure analysis
- digital twins
- spatial intelligence systems

---

# Why GeoAgents?

Most agent frameworks focus on:

- text reasoning
- retrieval
- general APIs

GeoAgents introduces **structured geospatial reasoning**.

The framework provides:

✔ spatial tool orchestration  
✔ GIS layer inference  
✔ reproducible spatial analysis  
✔ controlled LLM reasoning  
✔ modular architecture  

---

# Example

User question:

```

Are the points located inside the zones in this area?

```

GeoAgents will automatically:

1️⃣ generate a spatial plan  
2️⃣ select the correct tool (`spatial.intersects`)  
3️⃣ execute spatial analysis  
4️⃣ synthesize the result  

Example response:

```

Two intersections were detected between the points and Zone 1.
Points A and B intersect with the polygon area.

```

---

# Architecture

GeoAgents separates **reasoning**, **execution**, and **explanation**.

```

User Query
│
▼
Planner (LLM)
│
▼
Plan Validation
│
▼
Plan Postprocessor
│
▼
Execution Engine
│
▼
GIS Tools
│
▼
Facts Extraction
│
▼
Synthesizer (LLM)
│
▼
Final Response

```

Full diagrams available here:

```

docs/diagrams.md

```

---

# Core Concepts

## Agents

Agents define:

- system prompt
- allowed tools
- execution profile

Profiles:

```

compact
rich
investigate

```

---

## Tools

GeoAgents uses **GIS tools** to perform analysis.

Current tools:

```

spatial.intersects
spatial.nearby
spatial.query_layer
spatial.context_pack

````

Tools execute deterministic spatial logic.

---

## Layer Catalog

GeoAgents understands GIS datasets through a **layer catalog**.

Example:

```json
[
  {
    "name": "demo_points",
    "geometry": "POINT"
  },
  {
    "name": "demo_polygons",
    "geometry": "POLYGON"
  }
]
````

This allows the agent to automatically infer:

```
points
zones
lines
```

without knowing exact layer names.

---

# Installation

Clone the repository.

```
git clone https://github.com/your-org/geoagents.git
cd geoagents
```

Create a virtual environment.

```
python -m venv .venv
source .venv/bin/activate
```

Install dependencies.

```
pip install -r requirements.txt
```

Run migrations.

```
python manage.py migrate
```

Start the server.

```
python manage.py runserver
```

---

# Quick Start

Create an agent.

```python
from agents_core.models import Agent

agent = Agent.objects.create(
    name="geo-agent",
    system_prompt="You are an expert geospatial AI assistant.",
    profile="rich",
    tool_allowlist=[
        "spatial.intersects",
        "spatial.nearby",
        "spatial.query_layer",
        "spatial.context_pack"
    ]
)
```

Run an analysis.

```python
from agents_core.models import Run
from agents_core.runner import execute_run

run = Run.objects.create(
    agent=agent,
    input_json={
        "goal": "Check if the points are inside the zones",
        "map_context": {
            "bbox": {
                "west": -6.06,
                "south": 37.32,
                "east": -6.05,
                "north": 37.33
            }
        }
    }
)

execute_run(run)

print(run.final_text)
```

---

# API

GeoAgents exposes a REST API.

Example request:

```
POST /api/agents/{id}/run/
```

Request body:

```json
{
  "goal": "Analyze this area",
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

See full documentation:

```
docs/api.md
```

---

# Testing

A test script is included.

Run:

```
python test.py
```

This script evaluates multiple scenarios:

```
intersects
nearby
query_layer
summary
```

across different agent profiles.

---

# Documentation

Full documentation is available in the `docs` folder.

```
docs/
│
├── architecture.md
├── framework_diagrams.md
├── agents.md
├── tools.md
├── usage.md
├── api.md
```

---

# Extending GeoAgents

## Add a new tool

1️⃣ create a new tool in

```
agents_gis/tools/
```

2️⃣ register it in the tool registry

3️⃣ add rules in

```
plan_postprocessor.py
```

4️⃣ expose facts for the synthesizer

---

## Add new inference logic

Edit:

```
agents_gis/inference.py
```

Example:

```
infer_intersection_layers
infer_nearby_layer
infer_query_layer
```

---

# Roadmap

Planned features:

* raster analysis tools
* multi-step spatial reasoning
* spatial clustering
* route analysis
* memory-aware agents
* IoT spatial analytics
* 3D geospatial reasoning

---

# Contributing

Contributions are welcome.

Steps:

1️⃣ Fork the repository
2️⃣ Create a feature branch

```
git checkout -b feature/my-feature
```

3️⃣ Submit a pull request

---

# License

This project is released under the **MIT License**.

---

# Maintainer

GeoAgents is created and maintained by **Juan Manuel Quijada**  
Founder & CEO — Stratos Global Solutions

This project explores AI-driven geospatial reasoning and autonomous spatial analysis.

---

# Credits

GeoAgents is an experimental framework exploring the intersection of:

* AI agents
* spatial reasoning
* GIS analytics
* explainable geospatial intelligence

