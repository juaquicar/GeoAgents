from django.urls import path
from .views import GisLayerListAPIView

urlpatterns = [
    path("gis/layers/", GisLayerListAPIView.as_view(), name="gis-layers-list"),
]