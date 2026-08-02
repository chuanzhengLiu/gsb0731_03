from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import StoreViewSet, RoomViewSet


router = DefaultRouter()
router.register(r'stores', StoreViewSet, basename='store')
router.register(r'rooms', RoomViewSet, basename='room')

urlpatterns = [
    path('', include(router.urls)),
]
