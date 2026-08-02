from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    DMProfileViewSet,
    DMSkillViewSet,
    DMAvailabilityViewSet,
    DMTemporaryUnavailableViewSet,
)


router = DefaultRouter()
router.register(r'profiles', DMProfileViewSet, basename='dm-profile')
router.register(r'skills', DMSkillViewSet, basename='dm-skill')
router.register(r'availabilities', DMAvailabilityViewSet, basename='dm-availability')
router.register(r'temporary-unavailables', DMTemporaryUnavailableViewSet, basename='dm-temporary-unavailable')


urlpatterns = [
    path('', include(router.urls)),
]
