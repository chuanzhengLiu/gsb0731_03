import django_filters
from .models import Script, ScriptType, ScriptDifficulty, ScriptStatus


class PlayerCountFilter(django_filters.Filter):
    def filter(self, qs, value):
        if value is None:
            return qs
        try:
            count = int(value)
        except (TypeError, ValueError):
            return qs
        return qs.filter(**{f'player_count__total': count})


class ScriptFilter(django_filters.FilterSet):
    type = django_filters.MultipleChoiceFilter(
        choices=ScriptType.choices,
        field_name='type',
        lookup_expr='in'
    )
    difficulty = django_filters.MultipleChoiceFilter(
        choices=ScriptDifficulty.choices,
        field_name='difficulty',
        lookup_expr='in'
    )
    status = django_filters.ChoiceFilter(
        choices=ScriptStatus.choices,
        field_name='status'
    )
    player_count = PlayerCountFilter(
        field_name='player_count',
        label='玩家人数'
    )
    min_duration = django_filters.NumberFilter(
        field_name='duration_minutes',
        lookup_expr='gte',
        label='最小时长(分钟)'
    )
    max_duration = django_filters.NumberFilter(
        field_name='duration_minutes',
        lookup_expr='lte',
        label='最大时长(分钟)'
    )
    store = django_filters.NumberFilter(
        field_name='store_id',
        label='门店ID'
    )

    class Meta:
        model = Script
        fields = ['type', 'difficulty', 'status', 'player_count', 'store']
