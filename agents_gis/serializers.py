from rest_framework import serializers


class GisLayerIntrospectionSerializer(serializers.Serializer):
    name = serializers.CharField()
    table = serializers.CharField()
    geom_col = serializers.CharField()
    id_col = serializers.CharField()
    fields = serializers.ListField(child=serializers.CharField())
    filter_fields = serializers.ListField(child=serializers.CharField())