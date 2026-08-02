from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ScriptViewSet,
    RoleViewSet,
    ScriptRecommendationView,
)

router = DefaultRouter()
router.register(r'scripts', ScriptViewSet, basename='script')
router.register(r'roles', RoleViewSet, basename='role')

urlpatterns = [
    path('', include(router.urls)),
    path('recommend/', ScriptRecommendationView.as_view(), name='script-recommend'),
]
