from django.urls import path
from .views import GisLayerListAPIView, GisLayerFeaturesAPIView

urlpatterns = [
    path("gis/layers/", GisLayerListAPIView.as_view(), name="gis-layers-list"),
    path("gis/features/", GisLayerFeaturesAPIView.as_view(), name="gis-layer-features"),
]