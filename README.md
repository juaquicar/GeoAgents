# GeoAgents

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)]()
[![Django](https://img.shields.io/badge/django-4.x-green.svg)]()
[![PostGIS](https://img.shields.io/badge/postgis-enabled-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)]()

**GeoAgents** is an open-source framework for building **AI agents specialized in geospatial analysis (GIS)**.

It is designed to let AI agents:

* understand spatial questions
* select GIS tools automatically
* execute spatial analysis
* verify hypotheses about the results
* generate natural language explanations
* expose a full execution trace through API

GeoAgents is oriented to:

* GIS applications
* geospatial platforms
* telecom infrastructure analysis
* digital twins
* spatial intelligence systems

---

## Table of Contents

* [Why GeoAgents?](#why-geoagents)
* [What GeoAgents Does](#what-geoagents-does)
* [Example](#example)
* [Architecture](#architecture)
* [Core Concepts](#core-concepts)

  * [Agents](#agents)
  * [Tools](#tools)
  * [Layer Catalog](#layer-catalog)
  * [Runs, Verification and Trace](#runs-verification-and-trace)
* [Installation](#installation)
* [Quick Start](#quick-start)
* [API](#api)
* [Official Examples and Manual Regression](#official-examples-and-manual-regression)
* [Testing](#testing)
* [Documentation](#documentation)
* [Repository Structure](#repository-structure)
* [Extending GeoAgents](#extending-geoagents)
* [Roadmap](#roadmap)
* [Contributing](#contributing)
* [License](#license)
* [Maintainer](#maintainer)
* [Credits](#credits)

---

## Why GeoAgents?

Most agent frameworks focus on:

* text reasoning
* retrieval
* general APIs

GeoAgents introduces **structured geospatial reasoning**.

The framework provides:

* spatial tool orchestration
* GIS layer inference
* reproducible spatial analysis
* controlled LLM reasoning
* verifiable multi-step execution
* traceable runs through API
* modular architecture

---

## What GeoAgents Does

GeoAgents separates the lifecycle of a geospatial agent into explicit phases:

```text
plan -> execute -> verify -> optional replan -> synthesize
```

This means the framework is not limited to “calling one tool and returning text”. It can:

* build multi-step plans
* pass outputs from one step to another
* verify whether a hypothesis was confirmed or refuted
* replan when a step fails or evidence is insufficient
* persist the full execution trace for inspection and debugging

---

## Example

User question:

```text
Are the points located inside the zones in this area?
```

GeoAgents will typically:

1. generate a spatial plan
2. select the appropriate GIS tool, for example `spatial.intersects`
3. execute the analysis
4. verify the result if applicable
5. synthesize a final response

Example response:

```text
Two intersections were detected between the points and Zone 1.
Points A and B intersect with the polygon area.
```

---

## Architecture

GeoAgents separates **reasoning**, **execution**, **verification**, and **explanation**.

```text
User Query
│
▼
Planner (LLM)
│
▼
Plan Validation
│
▼
Plan Postprocessor / Normalization
│
▼
Runner
│
▼
GIS Tools
│
▼
Verification
│
▼
Optional Replan
│
▼
Synthesizer (LLM)
│
▼
Final Response
```

The runtime cycle can be summarized as:

```text
plan -> execute -> verify -> optional replan -> synthesize
```

Detailed docs:

```text
docs/architecture.md
docs/diagrams.md
```

---

## Core Concepts

### Agents

Agents define:

* system prompt
* allowed tools
* execution profile

Profiles:

```text
compact
rich
investigate
```

An agent does not execute tools by itself. It defines the reasoning and tool boundaries that the runner will use during a `Run`.

More details:

```text
docs/agents.md
```

---

### Tools

GeoAgents uses **GIS tools** to perform deterministic spatial operations.

Current core tools include:

```text
spatial.summary
spatial.query_layer
spatial.nearby
spatial.intersects
spatial.context_pack
spatial.network_trace
```

Tools can participate in:

* single-step analysis
* multi-step workflows
* hypothesis verification
* replan flows

More details:

```text
docs/tools.md
```

---

### Layer Catalog

GeoAgents understands datasets through a **layer catalog**.

Example:

```json
[
  {
    "name": "demo_points",
    "geometry_kind": "point"
  },
  {
    "name": "demo_lines",
    "geometry_kind": "line"
  },
  {
    "name": "demo_polygons",
    "geometry_kind": "polygon"
  }
]
```

This allows the agent to infer likely layers for concepts such as:

```text
points
zones
lines
```

without having to know the exact layer names in advance.

---

### Runs, Verification and Trace

Every execution is persisted as a `Run`.

A run may contain:

* input payload
* final plan
* plan history
* executed tool outputs
* verification summary
* final synthesized text
* full persisted step log

Verification states include:

```text
verified
refuted
inconclusive
not_evaluated
```

This makes the framework observable and suitable for:

* demos
* QA
* debugging
* auditability

API details:

```text
docs/api.md
```

---

## Installation

Clone the repository:

```bash
git clone https://github.com/juaquicar/GeoAgents.git
cd GeoAgents
```

Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run migrations:

```bash
python manage.py migrate
```

Start the server:

```bash
python manage.py runserver
```

---

## Quick Start

Create an agent:

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
        "spatial.context_pack",
        "spatial.network_trace",
    ],
)
```

Create and execute a run:

```python
from agents_core.models import Run
from agents_core.runner import execute_run

run = Run.objects.create(
    agent=agent,
    user=user,
    input_json={
        "goal": "Check if the points are inside the zones",
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
)

run = execute_run(run)

print(run.final_text)
print(run.output_json)
```

Usage guide:

```text
docs/usage.md
```

---

## API

GeoAgents exposes a REST API around:

* agents
* runs
* execution
* steps
* trace

Current base routes:

```text
/api/agents/agents/
/api/agents/runs/
```

Typical flow:

1. create a run
2. execute the run
3. inspect the run
4. inspect the trace

Example endpoints:

```text
POST /api/agents/runs/
POST /api/agents/runs/{id}/execute/
GET  /api/agents/runs/{id}/
GET  /api/agents/runs/{id}/steps/
GET  /api/agents/runs/{id}/trace/
```

Full API documentation:

```text
docs/api.md
```

---

## Official Examples and Manual Regression

GeoAgents includes a small official set of reproducible examples for:

* demo
* QA
* onboarding
* manual regression

Canonical examples covered:

* simple layer query
* multi-tool workflow with step references
* refuted hypothesis with basic replan

Main docs:

```text
docs/examples.md
docs/manual_regression.md
```

Payloads:

```text
examples/01_simple_layer_query.json
examples/02_multi_tool_with_references.json
examples/03_refuted_hypothesis_with_replan.json
```

These examples are also represented as canonical planner fixtures in:

```text
examples/canonical_plans.py
```

---

## Testing

Run core tests:

```bash
python manage.py test agents_core.tests
```

Run API tests:

```bash
python manage.py test agents_core.tests_api
```

Run the full test suite:

```bash
python manage.py test
```

GeoAgents now includes tests for:

* planner validation
* multi-step execution
* reference resolution
* verification states
* replan behavior
* API contract
* trace serialization

---

## Documentation

Full documentation is available in the `docs` folder.

```text
docs/
├── agents.md
├── api.md
├── architecture.md
├── diagrams.md
├── examples.md
├── manual_regression.md
├── tools.md
└── usage.md
```

Recommended reading order:

1. `docs/architecture.md`
2. `docs/agents.md`
3. `docs/tools.md`
4. `docs/api.md`
5. `docs/usage.md`
6. `docs/examples.md`
7. `docs/manual_regression.md`

---

## Repository Structure

High-level structure:

```text
GeoAgents/
├── agents_core/
├── agents_gis/
├── agents_llm/
├── agents_tools/
├── docs/
├── examples/
├── geoagents/
├── tests/
├── manage.py
├── requirements.txt
└── README.md
```

Main modules:

* `agents_core`: runner, models, API, serialization, step persistence
* `agents_llm`: planner, prompt client, postprocessor, synthesizer
* `agents_gis`: GIS inference and domain tools
* `agents_tools`: tool registry, execution layer and introspection
* `examples`: canonical examples and reproducible payloads
* `docs`: architecture, API, examples and usage guides

---

## Extending GeoAgents

### Add a new tool

Typical steps:

1. create the implementation file
2. implement the tool
3. register it in the tool registry
4. expose it in introspection if needed
5. add planner/postprocessor support
6. add synthesizer support if needed
7. add tests
8. document it

Relevant locations:

```text
agents_gis/
agents_tools/
agents_llm/plan_postprocessor.py
docs/tools.md
```

### Add new inference logic

Edit:

```text
agents_gis/inference.py
```

Typical inference areas:

```text
infer_intersection_layers
infer_nearby_layer
infer_query_layer
```

### Add new examples

Use:

```text
examples/
docs/examples.md
docs/manual_regression.md
```

---

## Roadmap

Planned and natural next steps include:

* persistent run memory
* episodic memory
* reusable heuristics
* execution budgets
* harder timeouts
* finer retry policies
* network-domain expansion
* advanced spatial analytics

Examples of planned tools:

* `spatial.route_cost`
* `spatial.network_service_area`
* `spatial.cluster`
* `spatial.visibility`

---

## Contributing

Contributions are welcome.

Typical flow:

1. fork the repository
2. create a feature branch

```bash
git checkout -b feature/my-feature
```

3. add tests and documentation
4. submit a pull request

When contributing, prefer changes that preserve:

* explicit contracts
* reproducible examples
* trace clarity
* deterministic tool behavior where possible

---

## License

This project is released under the **MIT License**.

---

## Maintainer

GeoAgents is created and maintained by **Juan Manuel Quijada**
Founder & CEO — Stratos Global Solutions

This project explores AI-driven geospatial reasoning and autonomous spatial analysis.

---

## Credits

GeoAgents is an experimental framework exploring the intersection of:

* AI agents
* spatial reasoning
* GIS analytics
* explainable geospatial intelligence
