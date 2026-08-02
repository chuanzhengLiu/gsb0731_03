from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ScheduleViewSet,
    SchedulingView,
    ReassignmentView,
    ConflictViewSet,
    ScheduleCalendarView,
)


router = DefaultRouter()
router.register(r'schedules', ScheduleViewSet, basename='schedule')
router.register(r'conflicts', ConflictViewSet, basename='conflict')


urlpatterns = [
    path('', include(router.urls)),

    path('run-scheduling/', SchedulingView.as_view(), name='run-scheduling'),

    path('reassign/', ReassignmentView.as_view(), name='reassign'),

    path('calendar/', ScheduleCalendarView.as_view(), name='schedule-calendar'),
]
