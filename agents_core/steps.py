import time
from typing import Any, Dict, Optional, Tuple

from django.db.models import F

from .models import Run, RunStep


def log_step(
    run: Run,
    kind: str,
    name: str = "",
    input_json: Optional[Dict[str, Any]] = None,
    output_json: Optional[Dict[str, Any]] = None,
    latency_ms: int = 0,
    error: str = "",
) -> RunStep:
    """
    Registra un paso del run con idx incremental atómico.
    """

    # incremento atómico del contador
    Run.objects.filter(pk=run.pk).update(step_seq=F("step_seq") + 1)

    # refrescar el valor actualizado
    run.refresh_from_db(fields=["step_seq"])
    idx = run.step_seq

    step = RunStep.objects.create(
        run=run,
        idx=idx,
        kind=kind,
        name=name,
        input_json=input_json or {},
        output_json=output_json or {},
        latency_ms=int(latency_ms or 0),
        error=error or "",
    )

    return step


def timed(fn, *args, **kwargs) -> Tuple[Any, int]:
    """
    Ejecuta fn y devuelve (resultado, latency_ms)
    """
    t0 = time.perf_counter()
    res = fn(*args, **kwargs)
    dt = (time.perf_counter() - t0) * 1000.0
    return res, int(dt)