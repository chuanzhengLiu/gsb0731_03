from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PlayerProfileViewSet,
    RoleAssignmentViewSet,
    RoleMatchView,
    PlayerHistoryView,
)


router = DefaultRouter()
router.register(r'profiles', PlayerProfileViewSet, basename='player-profile')
router.register(r'assignments', RoleAssignmentViewSet, basename='role-assignment')

urlpatterns = [
    path('', include(router.urls)),
    path('match/', RoleMatchView.as_view(), name='role-match'),
    path('player/<int:pk>/history/', PlayerHistoryView.as_view(), name='player-history'),
]
