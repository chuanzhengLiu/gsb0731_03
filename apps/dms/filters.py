import django_filters
from django.db.models import JSONField

from .models import DMProfile, DMSkill, DMAvailability, DMTemporaryUnavailable


class SpecialtyTypeFilter(django_filters.Filter):
    def filter(self, qs, value):
        if value is None or value == '':
            return qs
        values = [v.strip() for v in value.split(',') if v.strip()]
        if not values:
            return qs
        query = qs.none()
        for v in values:
            query |= qs.filter(specialty_types__contains=v)
        return query.distinct()


class DMProfileFilter(django_filters.FilterSet):
    specialty_type = SpecialtyTypeFilter(
        field_name='specialty_types',
        label='擅长类型(多个用逗号分隔)'
    )
    min_rating = django_filters.NumberFilter(
        field_name='avg_rating',
        lookup_expr='gte',
        label='最低评分'
    )
    max_rating = django_filters.NumberFilter(
        field_name='avg_rating',
        lookup_expr='lte',
        label='最高评分'
    )
    join_date_from = django_filters.DateFilter(
        field_name='join_date',
        lookup_expr='gte',
        label='入职日期起'
    )
    join_date_to = django_filters.DateFilter(
        field_name='join_date',
        lookup_expr='lte',
        label='入职日期止'
    )
    fatigue_warning = django_filters.BooleanFilter(
        field_name='fatigue_warning',
        label='疲劳预警'
    )
    min_total_sessions = django_filters.NumberFilter(
        field_name='total_sessions',
        lookup_expr='gte',
        label='最少带本场次'
    )
    max_consecutive_days = django_filters.NumberFilter(
        field_name='consecutive_days',
        lookup_expr='lte',
        label='最多连续工作天数'
    )

    class Meta:
        model = DMProfile
        fields = [
            'specialty_type',
            'min_rating',
            'max_rating',
            'join_date_from',
            'join_date_to',
            'fatigue_warning',
            'min_total_sessions',
            'max_consecutive_days',
        ]


class DMSkillFilter(django_filters.FilterSet):
    dm = django_filters.NumberFilter(
        field_name='dm_id',
        label='DM档案ID'
    )
    script = django_filters.NumberFilter(
        field_name='script_id',
        label='剧本ID'
    )
    min_proficiency = django_filters.NumberFilter(
        field_name='proficiency',
        lookup_expr='gte',
        label='最低熟练度'
    )
    max_proficiency = django_filters.NumberFilter(
        field_name='proficiency',
        lookup_expr='lte',
        label='最高熟练度'
    )
    min_play_count = django_filters.NumberFilter(
        field_name='play_count',
        lookup_expr='gte',
        label='最少带本次数'
    )
    last_played_from = django_filters.DateFilter(
        field_name='last_played',
        lookup_expr='gte',
        label='上次带本日期起'
    )
    last_played_to = django_filters.DateFilter(
        field_name='last_played',
        lookup_expr='lte',
        label='上次带本日期止'
    )
    script_type = django_filters.CharFilter(
        field_name='script__type',
        label='剧本类型'
    )

    class Meta:
        model = DMSkill
        fields = [
            'dm',
            'script',
            'min_proficiency',
            'max_proficiency',
            'min_play_count',
            'last_played_from',
            'last_played_to',
            'script_type',
        ]


class DMAvailabilityFilter(django_filters.FilterSet):
    dm = django_filters.NumberFilter(
        field_name='dm_id',
        label='DM档案ID'
    )
    day_of_week = django_filters.NumberFilter(
        field_name='day_of_week',
        label='星期几(0-6, 周一至周日)'
    )
    is_recurring = django_filters.BooleanFilter(
        field_name='is_recurring',
        label='是否循环'
    )
    specific_date = django_filters.DateFilter(
        field_name='specific_date',
        label='指定日期'
    )
    is_unavailable = django_filters.BooleanFilter(
        field_name='is_unavailable',
        label='是否临时不可用'
    )
    specific_date_from = django_filters.DateFilter(
        field_name='specific_date',
        lookup_expr='gte',
        label='指定日期起'
    )
    specific_date_to = django_filters.DateFilter(
        field_name='specific_date',
        lookup_expr='lte',
        label='指定日期止'
    )

    class Meta:
        model = DMAvailability
        fields = [
            'dm',
            'day_of_week',
            'is_recurring',
            'specific_date',
            'is_unavailable',
            'specific_date_from',
            'specific_date_to',
        ]


class DMTemporaryUnavailableFilter(django_filters.FilterSet):
    dm = django_filters.NumberFilter(
        field_name='dm_id',
        label='DM档案ID'
    )
    is_approved = django_filters.BooleanFilter(
        field_name='is_approved',
        label='是否已批准'
    )
    start_date_from = django_filters.DateFilter(
        field_name='start_date',
        lookup_expr='gte',
        label='开始日期起'
    )
    start_date_to = django_filters.DateFilter(
        field_name='start_date',
        lookup_expr='lte',
        label='开始日期止'
    )
    end_date_from = django_filters.DateFilter(
        field_name='end_date',
        lookup_expr='gte',
        label='结束日期起'
    )
    end_date_to = django_filters.DateFilter(
        field_name='end_date',
        lookup_expr='lte',
        label='结束日期止'
    )
    overlap_date = django_filters.DateFilter(
        method='filter_overlap_date',
        label='包含日期(查找该日期所在的请假区间)'
    )

    class Meta:
        model = DMTemporaryUnavailable
        fields = [
            'dm',
            'is_approved',
            'start_date_from',
            'start_date_to',
            'end_date_from',
            'end_date_to',
        ]

    def filter_overlap_date(self, queryset, name, value):
        return queryset.filter(
            start_date__lte=value,
            end_date__gte=value,
        )
