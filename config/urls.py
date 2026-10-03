from django.contrib import admin
from django.urls import include, path
from django.views.static import serve

from django.conf import settings

admin.site.site_header = "Generación de diplomas"
admin.site.site_title = "Diplomas"
admin.site.index_title = "Administración"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("diplomas.urls")),
    path("static/<path:path>", serve, {"document_root": settings.STATIC_ROOT}),
]
