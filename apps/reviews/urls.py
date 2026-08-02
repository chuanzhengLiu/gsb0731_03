from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ReviewViewSet,
    ScriptStatsViewSet,
    DashboardView,
)


router = DefaultRouter()
router.register(r'reviews', ReviewViewSet, basename='review')
router.register(r'script-stats', ScriptStatsViewSet, basename='script-stats')


urlpatterns = [
    path('', include(router.urls)),

    path('dashboard-stats/', DashboardView.as_view(), name='dashboard-stats'),
]
