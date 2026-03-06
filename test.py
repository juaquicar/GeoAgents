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
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoagents.settings")  # ajusta si tu proyecto tiene otro nombre
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from agents_core.models import Agent, Run  # noqa: E402
from agents_core.runner import execute_run  # noqa: E402


TEST_GOAL = "Analiza esta zona y comprueba si los puntos están dentro de las zonas, explicando además el contexto espacial general"
TEST_MAP_CONTEXT = {
    "bbox": {
        "west": -6.06,
        "south": 37.32,
        "east": -6.05,
        "north": 37.33,
    },
    "zoom": 18,
}

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

    # Reconciliar por si ya existía
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


def run_case(profile: str, goal: str, map_context: dict) -> dict:
    user = get_or_create_user()
    agent = get_or_create_agent(profile)

    run = Run.objects.create(
        agent=agent,
        user=user,
        input_json={
            "goal": goal,
            "map_context": map_context,
        },
        status="queued",
    )

    run = execute_run(run)
    run.refresh_from_db()

    output = run.output_json or {}
    plan = output.get("plan", {}) or {}
    meta = plan.get("_meta", {}) or {}

    return {
        "profile": profile,
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "steps": plan.get("steps", []),
        "raw_plan": meta.get("raw_plan", {}),
        "validated_plan": meta.get("validated_plan", {}),
        "normalized_plan": meta.get("normalized_plan", {}),
        "final_text": run.final_text or output.get("final_text", ""),
    }


def print_case_result(result: dict) -> None:
    print("=" * 100)
    print(f"PROFILE: {result['profile']}")
    print(f"RUN ID : {result['run_id']}")
    print(f"STATUS : {result['status']}")
    print(f"ERROR  : {result['error']}")
    print("-" * 100)

    print("STEPS:")
    print(json.dumps(result["steps"], ensure_ascii=False, indent=2))

    print("-" * 100)
    print("RAW PLAN:")
    print(json.dumps(result["raw_plan"], ensure_ascii=False, indent=2))

    print("-" * 100)
    print("NORMALIZED PLAN:")
    print(json.dumps(result["normalized_plan"], ensure_ascii=False, indent=2))

    print("-" * 100)
    print("FINAL TEXT:")
    print(result["final_text"])
    print()


def main():
    profiles = ["compact", "rich", "investigate"]

    results = []
    for profile in profiles:
        result = run_case(profile, TEST_GOAL, TEST_MAP_CONTEXT)
        results.append(result)
        print_case_result(result)

    print("=" * 100)
    print("RESUMEN COMPARATIVO")
    print("=" * 100)
    for r in results:
        tool_names = [s.get("name") for s in r["steps"] if s.get("type") == "tool"]
        print(
            f"- {r['profile']}: status={r['status']}, tools={tool_names}, final_text_len={len(r['final_text'])}"
        )


if __name__ == "__main__":
    main()