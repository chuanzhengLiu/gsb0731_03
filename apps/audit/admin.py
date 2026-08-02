import json

from django.contrib import admin
from django.db.models import JSONField
from django.forms import widgets
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import AuditAction, AuditLog, AuditStatus, AuditTargetType


class PrettyJSONWidget(widgets.Textarea):
    def format_value(self, value):
        try:
            value = json.dumps(json.loads(value), indent=2, ensure_ascii=False)
            row_lengths = [len(r) for r in value.split('\n')]
            self.attrs['rows'] = min(max(len(row_lengths) + 2, 10), 30)
            self.attrs['cols'] = min(max(max(row_lengths) + 2, 40), 120)
            return value
        except Exception:
            return super().format_value(value)


class CreatedAtFilter(admin.SimpleListFilter):
    title = _('创建时间')
    parameter_name = 'created_at'

    def lookups(self, request, model_admin):
        return (
            ('today', _('今天')),
            ('yesterday', _('昨天')),
            ('this_week', _('本周')),
            ('this_month', _('本月')),
            ('last_7_days', _('最近7天')),
            ('last_30_days', _('最近30天')),
        )

    def queryset(self, request, queryset):
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self.value() == 'today':
            return queryset.filter(created_at__gte=today_start)
        if self.value() == 'yesterday':
            yesterday_start = today_start - timedelta(days=1)
            return queryset.filter(
                created_at__gte=yesterday_start,
                created_at__lt=today_start,
            )
        if self.value() == 'this_week':
            week_start = today_start - timedelta(days=today_start.weekday())
            return queryset.filter(created_at__gte=week_start)
        if self.value() == 'this_month':
            month_start = today_start.replace(day=1)
            return queryset.filter(created_at__gte=month_start)
        if self.value() == 'last_7_days':
            week_ago = now - timedelta(days=7)
            return queryset.filter(created_at__gte=week_ago)
        if self.value() == 'last_30_days':
            month_ago = now - timedelta(days=30)
            return queryset.filter(created_at__gte=month_ago)
        return queryset


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'created_at',
        'username',
        'action_display',
        'target_type_display',
        'target_id',
        'target_name',
        'store_name',
        'ip_address',
        'status_display',
    ]
    list_display_links = ['id', 'created_at']
    list_filter = [
        CreatedAtFilter,
        'action',
        'target_type',
        'status',
        'store',
    ]
    search_fields = [
        'username',
        'target_name',
        'ip_address',
        'failure_reason',
        'target_id',
    ]
    readonly_fields = [
        'id',
        'created_at',
        'action_display',
        'target_type_display',
        'status_display',
        'store_name',
    ]
    fieldsets = (
        (_('基本信息'), {
            'fields': (
                'id',
                'created_at',
                'action',
                'action_display',
                'target_type',
                'target_type_display',
                'target_id',
                'target_name',
                'status',
                'status_display',
                'failure_reason',
            )
        }),
        (_('操作人信息'), {
            'fields': (
                'user',
                'username',
                'ip_address',
                'user_agent',
            )
        }),
        (_('门店信息'), {
            'fields': (
                'store',
                'store_name',
            )
        }),
        (_('详情'), {
            'fields': (
                'details',
            )
        }),
    )
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    list_per_page = 50
    list_max_show_all = 500

    formfield_overrides = {
        JSONField: {'widget': PrettyJSONWidget},
    }

    def action_display(self, obj):
        return obj.get_action_display()
    action_display.short_description = _('操作类型')

    def target_type_display(self, obj):
        return obj.get_target_type_display()
    target_type_display.short_description = _('目标类型')

    def status_display(self, obj):
        status = obj.status
        display = obj.get_status_display()
        if status == AuditStatus.SUCCESS:
            color = 'green'
        elif status == AuditStatus.FAILED:
            color = 'red'
        else:
            color = 'orange'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            display,
        )
    status_display.short_description = _('操作状态')

    def store_name(self, obj):
        return obj.store.name if obj.store else '-'
    store_name.short_description = _('门店名称')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
