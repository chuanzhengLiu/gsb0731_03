import django_filters
from django.db import models as django_models
from django.utils import timezone

from .models import Schedule, ScheduleConflict, ScheduleStatus, ConflictType


class ScheduleFilter(django_filters.FilterSet):
    start_date = django_filters.DateFilter(
        method='filter_start_date',
        label='开始日期',
    )
    end_date = django_filters.DateFilter(
        method='filter_end_date',
        label='结束日期',
    )
    date_range = django_filters.DateFromToRangeFilter(
        method='filter_date_range',
        label='日期范围',
    )
    dm = django_filters.NumberFilter(
        field_name='dm_id',
        label='DM ID',
    )
    room = django_filters.NumberFilter(
        field_name='room_id',
        label='房间 ID',
    )
    script = django_filters.NumberFilter(
        field_name='script_id',
        label='剧本 ID',
    )
    status = django_filters.ChoiceFilter(
        field_name='status',
        choices=ScheduleStatus.choices,
        label='状态',
    )
    is_locked = django_filters.BooleanFilter(
        field_name='is_locked',
        label='是否锁定',
    )
    store = django_filters.NumberFilter(
        method='filter_store',
        label='门店 ID',
    )
    booking = django_filters.NumberFilter(
        field_name='booking_id',
        label='预约 ID',
    )

    class Meta:
        model = Schedule
        fields = [
            'status', 'is_locked', 'dm', 'room', 'script',
            'start_date', 'end_date', 'store', 'booking',
        ]

    def filter_start_date(self, queryset, name, value):
        from django.apps import apps
        try:
            Booking = apps.get_model('bookings', 'Booking')
            booking_ids = Booking.objects.filter(
                scheduled_start__date__gte=value
            ).values_list('id', flat=True)
            return queryset.filter(booking_id__in=booking_ids)
        except LookupError:
            return queryset

    def filter_end_date(self, queryset, name, value):
        from django.apps import apps
        try:
            Booking = apps.get_model('bookings', 'Booking')
            booking_ids = Booking.objects.filter(
                scheduled_start__date__lte=value
            ).values_list('id', flat=True)
            return queryset.filter(booking_id__in=booking_ids)
        except LookupError:
            return queryset

    def filter_date_range(self, queryset, name, value):
        from django.apps import apps
        try:
            Booking = apps.get_model('bookings', 'Booking')
            qs = Booking.objects.all()
            if value.start:
                qs = qs.filter(scheduled_start__date__gte=value.start)
            if value.stop:
                qs = qs.filter(scheduled_start__date__lte=value.stop)
            booking_ids = qs.values_list('id', flat=True)
            return queryset.filter(booking_id__in=booking_ids)
        except LookupError:
            return queryset

    def filter_store(self, queryset, name, value):
        from django.apps import apps
        try:
            Room = apps.get_model('stores', 'Room')
            room_ids = Room.objects.filter(store_id=value).values_list('id', flat=True)
            return queryset.filter(room_id__in=room_ids)
        except LookupError:
            return queryset


class ScheduleConflictFilter(django_filters.FilterSet):
    conflict_type = django_filters.ChoiceFilter(
        field_name='conflict_type',
        choices=ConflictType.choices,
        label='冲突类型',
    )
    resolved = django_filters.BooleanFilter(
        field_name='resolved',
        label='是否已解决',
    )
    schedule = django_filters.NumberFilter(
        method='filter_schedule',
        label='排班 ID',
    )

    class Meta:
        model = ScheduleConflict
        fields = ['conflict_type', 'resolved', 'schedule']

    def filter_schedule(self, queryset, name, value):
        return queryset.filter(
            django_models.Q(schedule1_id=value) | django_models.Q(schedule2_id=value)
        )
