import json

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .introspection import export_gis_layers_catalog
from .serializers import GisLayerIntrospectionSerializer
from .service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection,
    qualified_table, quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


class GisLayerListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Si no hay BD global configurada, devolver lista vacía
        if not getattr(settings, "AGENTS_GIS_DB_ALIAS", ""):
            return Response([])
        layers = export_gis_layers_catalog()
        serializer = GisLayerIntrospectionSerializer(layers, many=True)
        return Response(serializer.data)


class GisLayerFeaturesAPIView(APIView):
    """
    GET /api/gis/features/?layer=<name>&west=<>&south=<>&east=<>&north=<>[&agent_id=<id>]

    Devuelve features GeoJSON de una capa filtradas por bbox.
    Si se pasa agent_id, usa el catálogo y conexiones de ese agente.
    El límite máximo viene de GIS_MAP_LAYER_MAX_FEATURES (settings/.env).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Contexto de agente opcional
        agent_id = request.query_params.get("agent_id")
        ctx_token = None
        if agent_id:
            from agents_core.models import Agent
            from agents_gis.context import set_agent_context, _current_agent as _ca
            try:
                agent_obj = Agent.objects.get(pk=int(agent_id))
                ctx_token = set_agent_context(agent_obj)
            except (Agent.DoesNotExist, ValueError):
                return Response({"error": "Agente no encontrado"}, status=404)

        try:
            return self._handle(request)
        finally:
            if ctx_token is not None:
                from agents_gis.context import _current_agent as _ca
                _ca.reset(ctx_token)

    def _handle(self, request):
        layer_name = request.query_params.get("layer", "").strip()
        if not layer_name:
            return Response({"error": "Parámetro 'layer' requerido"}, status=400)

        layer_cfg = _get_layer_cfg(layer_name)
        if not layer_cfg:
            return Response({"error": f"Capa '{layer_name}' no encontrada"}, status=404)

        try:
            west  = float(request.query_params["west"])
            south = float(request.query_params["south"])
            east  = float(request.query_params["east"])
            north = float(request.query_params["north"])
        except (KeyError, ValueError):
            return Response({"error": "Parámetros bbox requeridos: west, south, east, north"}, status=400)

        max_features = getattr(settings, "GIS_MAP_LAYER_MAX_FEATURES", 1000)

        table     = qualified_table(layer_cfg)
        geom_col  = layer_cfg.get("geom_col", "the_geom")
        qgeom     = quote_col(geom_col)
        srid      = get_layer_srid(layer_cfg)
        id_col    = layer_cfg.get("id_col", "id")
        fields    = layer_cfg.get("fields", [])
        geom4326  = geom_to_4326(qgeom, srid)
        envelope  = bbox_in_layer_srid(srid)

        select_cols   = [quote_col(id_col)] + [quote_col(f) for f in fields]
        select_fields = ", ".join(select_cols)

        with get_gis_connection(layer_cfg).cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*)::int FROM {table}"
                f" WHERE {qgeom} IS NOT NULL AND ST_Intersects({qgeom}, {envelope})",
                [west, south, east, north],
            )
            total = cur.fetchone()[0]

            cur.execute(
                f"""SELECT {select_fields},
                       ST_AsGeoJSON({geom4326}) AS geom_geojson
                    FROM {table}
                    WHERE {qgeom} IS NOT NULL
                      AND ST_Intersects({qgeom}, {envelope})
                    LIMIT %s""",
                [west, south, east, north, max_features],
            )
            rows = _fetchall_dict(cur)

        features = []
        for row in rows:
            geom_str = row.pop("geom_geojson", None)
            if not geom_str:
                continue
            try:
                geom = json.loads(geom_str)
            except Exception:
                continue
            features.append({"type": "Feature", "geometry": geom, "properties": row})

        return Response({
            "layer": layer_name,
            "total": total,
            "count": len(features),
            "max_features": max_features,
            "features": features,
        })
