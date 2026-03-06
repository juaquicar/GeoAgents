from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .introspection import export_gis_layers_catalog
from .serializers import GisLayerIntrospectionSerializer


class GisLayerListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        layers = export_gis_layers_catalog()
        serializer = GisLayerIntrospectionSerializer(layers, many=True)
        return Response(serializer.data)