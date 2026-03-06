from rest_framework import serializers


class ToolIntrospectionSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField()
    input_schema = serializers.JSONField()


