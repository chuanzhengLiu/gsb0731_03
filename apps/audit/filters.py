import django_filters
from django.db.models import Q

from .models import AuditAction, AuditLog, AuditStatus, AuditTargetType


class AuditLogFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='date__gte',
        label='开始日期',
    )
    date_to = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='date__lte',
        label='结束日期',
    )
    created_at_from = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        label='创建时间起',
    )
    created_at_to = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        label='创建时间止',
    )
    user_id = django_filters.NumberFilter(
        field_name='user_id',
        label='操作人用户ID',
    )
    username = django_filters.CharFilter(
        field_name='username',
        lookup_expr='icontains',
        label='用户名',
    )
    store = django_filters.NumberFilter(
        field_name='store_id',
        label='门店ID',
    )
    store_id = django_filters.NumberFilter(
        field_name='store_id',
        label='门店ID',
    )
    action = django_filters.ChoiceFilter(
        field_name='action',
        choices=AuditAction.choices,
        label='操作类型',
    )
    action_in = django_filters.MultipleChoiceFilter(
        field_name='action',
        choices=AuditAction.choices,
        label='操作类型（多选）',
    )
    target_type = django_filters.ChoiceFilter(
        field_name='target_type',
        choices=AuditTargetType.choices,
        label='目标类型',
    )
    target_type_in = django_filters.MultipleChoiceFilter(
        field_name='target_type',
        choices=AuditTargetType.choices,
        label='目标类型（多选）',
    )
    target_id = django_filters.NumberFilter(
        field_name='target_id',
        label='目标ID',
    )
    target_name = django_filters.CharFilter(
        field_name='target_name',
        lookup_expr='icontains',
        label='目标名称',
    )
    status = django_filters.ChoiceFilter(
        field_name='status',
        choices=AuditStatus.choices,
        label='操作状态',
    )
    ip_address = django_filters.CharFilter(
        field_name='ip_address',
        lookup_expr='icontains',
        label='操作IP',
    )
    search = django_filters.CharFilter(
        method='filter_search',
        label='关键词搜索（用户名、目标名称、IP）',
    )

    class Meta:
        model = AuditLog
        fields = [
            'date_from', 'date_to',
            'created_at_from', 'created_at_to',
            'user_id', 'username',
            'store', 'store_id',
            'action', 'action_in',
            'target_type', 'target_type_in',
            'target_id', 'target_name',
            'status',
            'ip_address',
        ]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(username__icontains=value) |
            Q(target_name__icontains=value) |
            Q(ip_address__icontains=value) |
            Q(failure_reason__icontains=value)
        )
