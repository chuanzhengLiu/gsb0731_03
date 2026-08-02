from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import BookingViewSet, BookingPlayerViewSet


router = DefaultRouter()
router.register(r'bookings', BookingViewSet, basename='booking')
router.register(r'booking-players', BookingPlayerViewSet, basename='booking-player')

urlpatterns = [
    path('', include(router.urls)),
]
