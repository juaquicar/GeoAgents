from rest_framework.routers import DefaultRouter

from .views import AgentViewSet, RunViewSet

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agents")
router.register(r"runs", RunViewSet, basename="runs")

urlpatterns = router.urls