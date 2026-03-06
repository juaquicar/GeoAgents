from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .introspection import export_tools_catalog
from .serializers import ToolIntrospectionSerializer


class ToolListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tools = export_tools_catalog()
        serializer = ToolIntrospectionSerializer(tools, many=True)
        return Response(serializer.data)
