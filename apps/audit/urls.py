from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AuditExportView, AuditLogViewSet


router = DefaultRouter()
router.register(r'logs', AuditLogViewSet, basename='audit-log')


urlpatterns = [
    path('', include(router.urls)),
    path('export/', AuditExportView.as_view(), name='audit-export'),
]
