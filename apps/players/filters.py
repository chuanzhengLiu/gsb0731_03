import django_filters
from django.db.models import Q

from .models import PlayerProfile, RoleAssignment


PREFERENCE_TAG_CHOICES = [
    ('推理型', '推理型'),
    ('情感型', '情感型'),
    ('活跃型', '活跃型'),
    ('沉浸型', '沉浸型'),
    ('搞笑型', '搞笑型'),
    ('领导型', '领导型'),
    ('辅助型', '辅助型'),
    ('新手型', '新手型'),
    ('老玩家型', '老玩家型'),
]


class PlayerProfileFilter(django_filters.FilterSet):
    phone = django_filters.CharFilter(
        field_name='phone',
        lookup_expr='icontains',
        label='手机号'
    )
    name = django_filters.CharFilter(
        field_name='name',
        lookup_expr='icontains',
        label='姓名'
    )
    keyword = django_filters.CharFilter(
        method='filter_keyword',
        label='关键词搜索（手机号或姓名）'
    )
    preference_tag = django_filters.ChoiceFilter(
        method='filter_preference_tag',
        choices=PREFERENCE_TAG_CHOICES,
        label='偏好标签'
    )
    has_preference_tags = django_filters.BooleanFilter(
        method='filter_has_preference_tags',
        label='是否有偏好标签'
    )
    horror_tolerance = django_filters.NumberFilter(
        field_name='horror_tolerance',
        label='恐怖耐受度'
    )
    horror_tolerance_gte = django_filters.NumberFilter(
        field_name='horror_tolerance',
        lookup_expr='gte',
        label='恐怖耐受度大于等于'
    )
    horror_tolerance_lte = django_filters.NumberFilter(
        field_name='horror_tolerance',
        lookup_expr='lte',
        label='恐怖耐受度小于等于'
    )
    accept_reverse = django_filters.BooleanFilter(
        field_name='accept_reverse',
        label='是否接受反串'
    )
    last_visit_from = django_filters.DateFilter(
        method='filter_last_visit_from',
        label='最近到访日期从'
    )
    last_visit_to = django_filters.DateFilter(
        method='filter_last_visit_to',
        label='最近到访日期至'
    )
    total_plays_gte = django_filters.NumberFilter(
        method='filter_total_plays_gte',
        label='总场次大于等于'
    )
    total_plays_lte = django_filters.NumberFilter(
        method='filter_total_plays_lte',
        label='总场次小于等于'
    )
    created_from = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        label='创建时间从'
    )
    created_to = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        label='创建时间至'
    )

    class Meta:
        model = PlayerProfile
        fields = [
            'phone', 'name', 'keyword',
            'preference_tag', 'has_preference_tags',
            'horror_tolerance', 'horror_tolerance_gte', 'horror_tolerance_lte',
            'accept_reverse',
            'last_visit_from', 'last_visit_to',
            'total_plays_gte', 'total_plays_lte',
            'created_from', 'created_to',
        ]

    def filter_keyword(self, queryset, name, value):
        return queryset.filter(
            Q(phone__icontains=value) |
            Q(name__icontains=value)
        )

    def filter_preference_tag(self, queryset, name, value):
        return queryset.filter(
            preference_tags__contains=[value]
        )

    def filter_has_preference_tags(self, queryset, name, value):
        if value:
            return queryset.exclude(
                Q(preference_tags=[]) | Q(preference_tags__isnull=True)
            )
        else:
            return queryset.filter(
                Q(preference_tags=[]) | Q(preference_tags__isnull=True)
            )

    def filter_last_visit_from(self, queryset, name, value):
        date_str = value.isoformat()
        ids = []
        for profile in queryset:
            history = profile.history_roles or []
            dates = [r.get('date') for r in history if r.get('date')]
            if dates and max(dates) >= date_str:
                ids.append(profile.id)
        return queryset.filter(id__in=ids)

    def filter_last_visit_to(self, queryset, name, value):
        date_str = value.isoformat()
        ids = []
        for profile in queryset:
            history = profile.history_roles or []
            dates = [r.get('date') for r in history if r.get('date')]
            if not dates or max(dates) <= date_str:
                ids.append(profile.id)
        return queryset.filter(id__in=ids)

    def filter_total_plays_gte(self, queryset, name, value):
        ids = []
        for profile in queryset:
            if len(profile.history_roles or []) >= value:
                ids.append(profile.id)
        return queryset.filter(id__in=ids)

    def filter_total_plays_lte(self, queryset, name, value):
        ids = []
        for profile in queryset:
            if len(profile.history_roles or []) <= value:
                ids.append(profile.id)
        return queryset.filter(id__in=ids)


class RoleAssignmentFilter(django_filters.FilterSet):
    schedule = django_filters.NumberFilter(
        field_name='schedule_id',
        label='场次ID'
    )
    player_profile = django_filters.NumberFilter(
        field_name='player_profile_id',
        label='玩家档案ID'
    )
    role = django_filters.NumberFilter(
        field_name='role_id',
        label='角色ID'
    )
    player_name = django_filters.CharFilter(
        field_name='player_name',
        lookup_expr='icontains',
        label='玩家姓名'
    )
    player_phone = django_filters.CharFilter(
        field_name='player_phone',
        lookup_expr='icontains',
        label='玩家电话'
    )
    match_score_gte = django_filters.NumberFilter(
        field_name='match_score',
        lookup_expr='gte',
        label='匹配度大于等于'
    )
    match_score_lte = django_filters.NumberFilter(
        field_name='match_score',
        lookup_expr='lte',
        label='匹配度小于等于'
    )
    is_manual_adjusted = django_filters.BooleanFilter(
        field_name='is_manual_adjusted',
        label='是否手动调整'
    )
    has_satisfaction = django_filters.BooleanFilter(
        method='filter_has_satisfaction',
        label='是否有满意度评分'
    )
    assigned_from = django_filters.DateTimeFilter(
        field_name='assigned_at',
        lookup_expr='gte',
        label='分配时间从'
    )
    assigned_to = django_filters.DateTimeFilter(
        field_name='assigned_at',
        lookup_expr='lte',
        label='分配时间至'
    )

    class Meta:
        model = RoleAssignment
        fields = [
            'schedule', 'player_profile', 'role',
            'player_name', 'player_phone',
            'match_score_gte', 'match_score_lte',
            'is_manual_adjusted', 'has_satisfaction',
            'assigned_from', 'assigned_to',
        ]

    def filter_has_satisfaction(self, queryset, name, value):
        if value:
            return queryset.filter(satisfaction__isnull=False)
        else:
            return queryset.filter(satisfaction__isnull=True)
