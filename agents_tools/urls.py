from django.urls import path
from .views import ToolListAPIView

urlpatterns = [
    path("tools/", ToolListAPIView.as_view(), name="tools-list"),
]