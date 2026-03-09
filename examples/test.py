import json
import os
import sys
from pathlib import Path

import django

# -----------------------------------------------------------------------------
# Bootstrap Django
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoagents.settings")  # ajusta si cambia
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from agents_core.models import Agent, Run  # noqa: E402
from agents_core.runner import execute_run  # noqa: E402


TEST_CASES = [
    {
        "name": "intersects_simple",
        "goal": "Comprueba la relación espacial entre los puntos y las zonas en esta área",
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
    {
        "name": "nearby_simple",
        "goal": "¿Qué elementos hay cerca del centro del mapa?",
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
    {
        "name": "summary_simple",
        "goal": "Analiza espacialmente esta zona y resume los elementos detectados",
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
    {
        "name": "mixed_context_intersects",
        "goal": "Analiza esta zona y comprueba si los puntos están dentro de las zonas, explicando además el contexto espacial general",
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
    {
        "name": "query_points_layer",
        "goal": "Explora la capa de puntos en esta zona",
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
    {
        "name": "query_polygons_layer",
        "goal": "Consulta la capa de zonas en esta área",
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
]

PROFILES = ["compact", "rich", "investigate"]

TOOL_ALLOWLIST = [
    "spatial.summary",
    "spatial.query_layer",
    "spatial.nearby",
    "spatial.intersects",
    "spatial.context_pack",
]


def get_or_create_user():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_geoagents",
        defaults={"email": "test_geoagents@example.com"},
    )
    return user


def get_or_create_agent(profile: str) -> Agent:
    agent, _ = Agent.objects.get_or_create(
        name=f"test-agent-{profile}",
        defaults={
            "system_prompt": "Eres un agente espacial de pruebas.",
            "is_active": True,
            "tool_allowlist": TOOL_ALLOWLIST,
            "profile": profile,
        },
    )

    changed = False

    if agent.profile != profile:
        agent.profile = profile
        changed = True

    if agent.tool_allowlist != TOOL_ALLOWLIST:
        agent.tool_allowlist = TOOL_ALLOWLIST
        changed = True

    if not agent.is_active:
        agent.is_active = True
        changed = True

    if changed:
        agent.save()

    return agent


def extract_tool_names(steps: list) -> list[str]:
    return [s.get("name") for s in steps if s.get("type") == "tool"]


def run_case(profile: str, case: dict) -> dict:
    user = get_or_create_user()
    agent = get_or_create_agent(profile)

    run = Run.objects.create(
        agent=agent,
        user=user,
        input_json={
            "goal": case["goal"],
            "map_context": case["map_context"],
        },
        status="queued",
    )

    run = execute_run(run)
    run.refresh_from_db()

    output = run.output_json or {}
    plan = output.get("plan", {}) or {}
    meta = plan.get("_meta", {}) or {}

    return {
        "case_name": case["name"],
        "goal": case["goal"],
        "profile": profile,
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "steps": plan.get("steps", []),
        "tool_names": extract_tool_names(plan.get("steps", [])),
        "raw_plan": meta.get("raw_plan", {}),
        "validated_plan": meta.get("validated_plan", {}),
        "normalized_plan": meta.get("normalized_plan", {}),
        "final_text": run.final_text or output.get("final_text", ""),
    }


def print_case_result(result: dict) -> None:
    print("=" * 110)
    print(f"CASE    : {result['case_name']}")
    print(f"PROFILE : {result['profile']}")
    print(f"RUN ID  : {result['run_id']}")
    print(f"STATUS  : {result['status']}")
    print(f"ERROR   : {result['error']}")
    print(f"GOAL    : {result['goal']}")
    print("-" * 110)

    print("TOOLS:")
    print(result["tool_names"])

    print("-" * 110)
    print("STEPS:")
    print(json.dumps(result["steps"], ensure_ascii=False, indent=2))

    print("-" * 110)
    print("RAW PLAN:")
    print(json.dumps(result["raw_plan"], ensure_ascii=False, indent=2))

    print("-" * 110)
    print("VALIDATED PLAN:")
    print(json.dumps(result["validated_plan"], ensure_ascii=False, indent=2))

    print("-" * 110)
    print("NORMALIZED PLAN:")
    print(json.dumps(result["normalized_plan"], ensure_ascii=False, indent=2))

    print("-" * 110)
    print("FINAL TEXT:")
    print(result["final_text"])
    print()


def summarize_results(results: list[dict]) -> None:
    print("=" * 110)
    print("RESUMEN COMPARATIVO")
    print("=" * 110)

    for r in results:
        print(
            f"- case={r['case_name']}, profile={r['profile']}, "
            f"status={r['status']}, tools={r['tool_names']}, final_text_len={len(r['final_text'])}"
        )


def print_case_matrix(results: list[dict]) -> None:
    print("=" * 110)
    print("MATRIZ POR CASO")
    print("=" * 110)

    grouped = {}
    for r in results:
        grouped.setdefault(r["case_name"], []).append(r)

    for case_name, rows in grouped.items():
        print(f"\nCASE: {case_name}")
        for row in sorted(rows, key=lambda x: x["profile"]):
            print(
                f"  - {row['profile']:<12} status={row['status']:<10} "
                f"tools={row['tool_names']} len={len(row['final_text'])}"
            )


def main():
    results = []

    for case in TEST_CASES:
        for profile in PROFILES:
            result = run_case(profile, case)
            results.append(result)
            print_case_result(result)

    summarize_results(results)
    print_case_matrix(results)


if __name__ == "__main__":
    main()