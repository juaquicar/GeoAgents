from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Agent, Run, RunFeedback, RunStep
from .serializers import (
    AgentSerializer,
    RunSerializer,
    RunStepSerializer,
    RunTraceSerializer,
)
from .runner import execute_run


def _fix_envelope_srid(sql: str, catalog: list) -> str:
    """
    Corrige el SRID en llamadas ST_MakeEnvelope(..., 4326) que no estén ya
    envueltas en ST_Transform cuando la capa referenciada tiene un SRID distinto
    de 4326 (p.ej. 25830 UTM).

    Sin esta corrección, ST_Intersects(geom_25830, envelope_4326) devuelve
    siempre 0 filas porque PostGIS compara coordenadas en proyecciones distintas.
    """
    import re

    # Tablas referenciadas en FROM/JOIN (sin schema prefix)
    table_re = re.compile(r'\b(?:FROM|JOIN)\s+(?:\w+\.)?(\w+)\b', re.IGNORECASE)
    referenced = {m.group(1).lower() for m in table_re.finditer(sql)}

    # Buscar SRID de la primera capa catalogada que no sea 4326
    layer_srid = None
    for layer in catalog:
        table = (layer.get("table") or "").lower().split(".")[-1]
        if table in referenced:
            srid = layer.get("srid")
            if srid and int(srid) != 4326:
                layer_srid = int(srid)
                break

    if not layer_srid:
        return sql

    envelope_re = re.compile(
        r'ST_MakeEnvelope\(\s*[-\d.]+\s*,\s*[-\d.]+\s*,\s*[-\d.]+\s*,\s*[-\d.]+\s*,\s*4326\s*\)',
        re.IGNORECASE,
    )

    def maybe_wrap(m):
        # No envolver si ya está dentro de ST_Transform(
        before = sql[: m.start()]
        if re.search(r'ST_Transform\s*\(\s*$', before, re.IGNORECASE):
            return m.group(0)
        return f"ST_Transform({m.group(0)}, {layer_srid})"

    return envelope_re.sub(maybe_wrap, sql)


def _apply_feedback_to_episode(run, rating: int) -> None:
    """
    Actualiza Episode.success con la valoración del usuario y recalcula
    EpisodePattern.success_rate para que los pattern_hints mejoren con el tiempo.
    """
    from .models import Episode, EpisodePattern
    try:
        episode = run.episode
    except Exception:
        return

    user_success = rating == 1
    episode.success = user_success
    episode.save(update_fields=["success", "updated_at"])

    matching = Episode.objects.filter(
        goal_signature=episode.goal_signature,
        domain=episode.domain,
        tool_sequence_signature=episode.tool_sequence_signature,
    )
    sample_size = matching.count()
    success_count = matching.filter(success=True).count()

    EpisodePattern.objects.filter(
        goal_signature=episode.goal_signature,
        domain=episode.domain,
        tool_sequence_signature=episode.tool_sequence_signature,
    ).update(
        sample_size=sample_size,
        success_count=success_count,
        failure_count=sample_size - success_count,
        success_rate=success_count / sample_size if sample_size else 0.0,
    )


def _run_inspect(agent):
    """
    Ejecuta la introspección GIS del agente y persiste el catálogo.
    No lanza excepciones — los errores se devuelven como string en gis_layers_catalog.
    """
    from agents_gis.inspect import inspect_agent_gis
    from django.utils import timezone
    try:
        catalog = inspect_agent_gis(agent)
        agent.gis_layers_catalog = catalog
        agent.gis_catalog_updated_at = timezone.now()
        agent.save(update_fields=["gis_layers_catalog", "gis_catalog_updated_at"])
        return None  # sin error
    except Exception as exc:
        return str(exc)


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all().order_by("-id")
    serializer_class = AgentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        agent = serializer.save()
        if agent.gis_db_connections:
            _run_inspect(agent)

    def perform_update(self, serializer):
        # Re-inspeccionar solo si el payload incluye gis_db_connections
        agent = serializer.save()
        if "gis_db_connections" in self.request.data and agent.gis_db_connections:
            _run_inspect(agent)

    @action(detail=True, methods=["post"])
    def inspect(self, request, pk=None):
        """POST /api/agents/{id}/inspect/ — Dispara la introspección GIS manualmente."""
        agent = self.get_object()
        if not agent.gis_db_connections:
            return Response(
                {"error": "El agente no tiene conexiones GIS configuradas."},
                status=400,
            )
        error = _run_inspect(agent)
        agent.refresh_from_db()
        data = AgentSerializer(agent).data
        if error:
            data["inspect_error"] = error
        return Response(data)


class RunViewSet(viewsets.ModelViewSet):
    queryset = Run.objects.select_related("agent", "memory", "episode").all().order_by("-id")
    serializer_class = RunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            Run.objects.select_related("agent", "memory", "episode")
            .filter(user=self.request.user)
            .order_by("-id")
        )

        params = self.request.query_params
        tool = (params.get("tool") or "").strip().lower()
        layer = (params.get("layer") or "").strip().lower()
        analysis_type = (params.get("analysis_type") or "").strip().lower()
        verification_status = (params.get("verification_status") or "").strip().lower()
        domain = (params.get("domain") or "").strip().lower()
        goal_signature = (params.get("goal_signature") or "").strip().lower()

        if tool:
            qs = qs.filter(memory__tools_search__icontains=tool)
        if layer:
            qs = qs.filter(memory__layers_search__icontains=layer)
        if analysis_type:
            qs = qs.filter(memory__analysis_types_search__icontains=analysis_type)
        if verification_status:
            qs = qs.filter(memory__verification_status=verification_status)
        if domain:
            qs = qs.filter(memory__domain=domain)
        if goal_signature:
            qs = qs.filter(memory__goal_signature__icontains=goal_signature)

        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        run = self.get_object()
        run = execute_run(run)
        return Response(RunSerializer(run).data)

    @action(detail=True, methods=["get"])
    def steps(self, request, pk=None):
        run = self.get_object()
        qs = RunStep.objects.filter(run=run).order_by("idx")
        return Response(RunStepSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"])
    def trace(self, request, pk=None):
        run = self.get_object()
        return Response(RunTraceSerializer(run).data)

    @action(detail=True, methods=["get"])
    def geojson(self, request, pk=None):
        """
        GET /api/runs/{id}/geojson/
        Ejecuta final_sql del run y devuelve un GeoJSON FeatureCollection.
        Requiere que el run tenga final_sql no vacío.
        """
        import re as _re
        from django.conf import settings as dj_settings
        from agents_gis.context import set_agent_context, _current_agent
        from agents_gis.service import get_gis_connection
        from .sql_guard import validate_sql

        run = self.get_object()

        if not run.final_sql:
            return Response(
                {"error": "Este run no tiene final_sql disponible."},
                status=400,
            )

        limit = getattr(dj_settings, "AGENTS_FINAL_GEOJSON_LIMIT", 100)

        # Sustituir el placeholder :limit por el valor real
        sql = run.final_sql.replace(":limit", str(int(limit)))

        # Validar de nuevo contra el catálogo actual del agente (defensa en profundidad)
        catalog = list(run.agent.gis_layers_catalog or [])
        allowed_tables = [layer.get("table") for layer in catalog if layer.get("table")]
        try:
            sql = validate_sql(sql, allowed_tables=allowed_tables or None)
        except ValueError as exc:
            return Response({"error": f"SQL no válido: {exc}"}, status=400)

        # Corregir SRID: si la capa tiene SRID ≠ 4326, envolver ST_MakeEnvelope(...,4326)
        # desnudos en ST_Transform para evitar 0 resultados por incompatibilidad de SRID
        sql = _fix_envelope_srid(sql, catalog)

        # Asegurarse de que hay LIMIT en la query (protección ante SQL sin LIMIT)
        if not _re.search(r"\bLIMIT\b", sql, _re.IGNORECASE):
            sql = f"{sql.rstrip(';')} LIMIT {limit}"

        # Inyectar contexto GIS del agente para usar su conexión
        _ctx_token = set_agent_context(run.agent)
        try:
            conn = get_gis_connection()
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
        except Exception as exc:
            return Response({"error": f"Error ejecutando SQL: {exc}"}, status=500)
        finally:
            _current_agent.reset(_ctx_token)

        features = []
        for row in rows:
            row_dict = dict(zip(cols, row))
            geom_geojson = row_dict.pop("geom_geojson", None)
            if not geom_geojson:
                continue
            import json as _json
            try:
                geometry = _json.loads(geom_geojson) if isinstance(geom_geojson, str) else geom_geojson
            except Exception:
                continue
            # Serializar valores no-JSON-nativos
            props = {}
            for k, v in row_dict.items():
                if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                    props[k] = float(v)
                elif v is None or isinstance(v, (str, int, float, bool)):
                    props[k] = v
                else:
                    props[k] = str(v)
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            })

        return Response({
            "type": "FeatureCollection",
            "features": features,
            "run_id": run.pk,
            "total": len(features),
        })

    @action(detail=True, methods=["post"])
    def feedback(self, request, pk=None):
        """
        POST /api/runs/{id}/feedback/
        Body: {"rating": 1 | -1, "comment": "..."}

        Guarda la valoración del usuario y actualiza Episode.success
        y EpisodePattern.success_rate con la señal real del usuario.
        """
        run = self.get_object()

        rating = request.data.get("rating")
        if rating not in (1, -1):
            return Response({"error": "rating must be 1 or -1"}, status=400)

        comment = (request.data.get("comment") or "").strip()

        feedback, _ = RunFeedback.objects.update_or_create(
            run=run,
            defaults={"user": request.user, "rating": rating, "comment": comment},
        )

        _apply_feedback_to_episode(run, rating)

        return Response({
            "run": run.pk,
            "rating": rating,
            "comment": comment,
        }, status=200)
