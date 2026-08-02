import django_filters
from django.db import models as django_models

from .models import Review, ScriptStats


class ReviewFilter(django_filters.FilterSet):
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
    store = django_filters.NumberFilter(
        method='filter_store',
        label='门店 ID',
    )
    script = django_filters.NumberFilter(
        method='filter_script',
        label='剧本 ID',
    )
    dm = django_filters.NumberFilter(
        method='filter_dm',
        label='DM ID',
    )
    has_player_review = django_filters.BooleanFilter(
        method='filter_has_player_review',
        label='是否有玩家评价',
    )
    has_dm_review = django_filters.BooleanFilter(
        method='filter_has_dm_review',
        label='是否有DM复盘',
    )
    dm_rating_min = django_filters.NumberFilter(
        field_name='dm_rating',
        lookup_expr='gte',
        label='DM评分最低',
    )
    dm_rating_max = django_filters.NumberFilter(
        field_name='dm_rating',
        lookup_expr='lte',
        label='DM评分最高',
    )
    script_rating_min = django_filters.NumberFilter(
        field_name='script_rating',
        lookup_expr='gte',
        label='剧本评分最低',
    )
    script_rating_max = django_filters.NumberFilter(
        field_name='script_rating',
        lookup_expr='lte',
        label='剧本评分最高',
    )

    class Meta:
        model = Review
        fields = [
            'start_date', 'end_date', 'date_range',
            'store', 'script', 'dm',
            'has_player_review', 'has_dm_review',
            'dm_rating_min', 'dm_rating_max',
            'script_rating_min', 'script_rating_max',
        ]

    def filter_start_date(self, queryset, name, value):
        from django.apps import apps
        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            Booking = apps.get_model('bookings', 'Booking')
            booking_ids = Booking.objects.filter(
                scheduled_start__date__gte=value
            ).values_list('id', flat=True)
            schedule_ids = Schedule.objects.filter(
                booking_id__in=booking_ids
            ).values_list('id', flat=True)
            return queryset.filter(schedule_id__in=schedule_ids)
        except LookupError:
            return queryset.filter(created_at__date__gte=value)

    def filter_end_date(self, queryset, name, value):
        from django.apps import apps
        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            Booking = apps.get_model('bookings', 'Booking')
            booking_ids = Booking.objects.filter(
                scheduled_start__date__lte=value
            ).values_list('id', flat=True)
            schedule_ids = Schedule.objects.filter(
                booking_id__in=booking_ids
            ).values_list('id', flat=True)
            return queryset.filter(schedule_id__in=schedule_ids)
        except LookupError:
            return queryset.filter(created_at__date__lte=value)

    def filter_date_range(self, queryset, name, value):
        from django.apps import apps
        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            Booking = apps.get_model('bookings', 'Booking')
            qs = Booking.objects.all()
            if value.start:
                qs = qs.filter(scheduled_start__date__gte=value.start)
            if value.stop:
                qs = qs.filter(scheduled_start__date__lte=value.stop)
            booking_ids = qs.values_list('id', flat=True)
            schedule_ids = Schedule.objects.filter(
                booking_id__in=booking_ids
            ).values_list('id', flat=True)
            return queryset.filter(schedule_id__in=schedule_ids)
        except LookupError:
            qs = queryset
            if value.start:
                qs = qs.filter(created_at__date__gte=value.start)
            if value.stop:
                qs = qs.filter(created_at__date__lte=value.stop)
            return qs

    def filter_store(self, queryset, name, value):
        from django.apps import apps
        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            Room = apps.get_model('stores', 'Room')
            room_ids = Room.objects.filter(store_id=value).values_list('id', flat=True)
            schedule_ids = Schedule.objects.filter(
                room_id__in=room_ids
            ).values_list('id', flat=True)
            return queryset.filter(schedule_id__in=schedule_ids)
        except LookupError:
            return queryset

    def filter_script(self, queryset, name, value):
        from django.apps import apps
        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            schedule_ids = Schedule.objects.filter(
                script_id=value
            ).values_list('id', flat=True)
            return queryset.filter(schedule_id__in=schedule_ids)
        except LookupError:
            return queryset

    def filter_dm(self, queryset, name, value):
        from django.apps import apps
        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            schedule_ids = Schedule.objects.filter(
                dm_id=value
            ).values_list('id', flat=True)
            return queryset.filter(schedule_id__in=schedule_ids)
        except LookupError:
            return queryset

    def filter_has_player_review(self, queryset, name, value):
        if value:
            return queryset.filter(
                django_models.Q(dm_rating__isnull=False) |
                django_models.Q(script_rating__isnull=False)
            )
        else:
            return queryset.filter(
                dm_rating__isnull=True,
                script_rating__isnull=True,
            )

    def filter_has_dm_review(self, queryset, name, value):
        if value:
            return queryset.exclude(
                django_models.Q(dm_review={}) |
                django_models.Q(dm_review__isnull=True)
            )
        else:
            return queryset.filter(
                django_models.Q(dm_review={}) |
                django_models.Q(dm_review__isnull=True)
            )


class ScriptStatsFilter(django_filters.FilterSet):
    script_type = django_filters.CharFilter(
        method='filter_script_type',
        label='剧本类型',
    )
    store = django_filters.NumberFilter(
        method='filter_store',
        label='门店 ID',
    )
    avg_rating_min = django_filters.NumberFilter(
        method='filter_avg_rating_min',
        label='平均评分最低',
    )
    avg_rating_max = django_filters.NumberFilter(
        method='filter_avg_rating_max',
        label='平均评分最高',
    )
    turnover_min = django_filters.NumberFilter(
        field_name='turnover_rate',
        lookup_expr='gte',
        label='周转率最低',
    )
    turnover_max = django_filters.NumberFilter(
        field_name='turnover_rate',
        lookup_expr='lte',
        label='周转率最高',
    )
    completion_min = django_filters.NumberFilter(
        field_name='completion_rate',
        lookup_expr='gte',
        label='完场率最低(%)',
    )

    class Meta:
        model = ScriptStats
        fields = [
            'script_type', 'store',
            'avg_rating_min', 'avg_rating_max',
            'turnover_min', 'turnover_max',
            'completion_min',
        ]

    def filter_script_type(self, queryset, name, value):
        from django.apps import apps
        try:
            Script = apps.get_model('scripts', 'Script')
            script_ids = Script.objects.filter(
                type=value
            ).values_list('id', flat=True)
            return queryset.filter(script_id__in=script_ids)
        except LookupError:
            return queryset

    def filter_store(self, queryset, name, value):
        from django.apps import apps
        try:
            Script = apps.get_model('scripts', 'Script')
            script_ids = Script.objects.filter(
                store_id=value
            ).values_list('id', flat=True)
            return queryset.filter(script_id__in=script_ids)
        except LookupError:
            return queryset

    def filter_avg_rating_min(self, queryset, name, value):
        return queryset.filter(
            django_models.Q(avg_script_rating__gte=value) |
            django_models.Q(avg_dm_rating__gte=value)
        )

    def filter_avg_rating_max(self, queryset, name, value):
        return queryset.filter(
            avg_script_rating__lte=value,
            avg_dm_rating__lte=value,
        )
