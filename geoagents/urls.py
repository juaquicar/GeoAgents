from django.contrib import admin
from django.urls import path, include
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("agents_core.urls")),
    path("api/", include("agents_tools.urls")),
    path("api/", include("agents_gis.urls")),
    path("api/token/", obtain_auth_token),

]