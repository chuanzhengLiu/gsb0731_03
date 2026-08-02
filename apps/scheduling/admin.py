from django.contrib import admin
from django.utils.html import format_html
from django.db.models.functions import TruncDate

from .models import Schedule, ScheduleConflict, ScheduleStatus, ConflictType


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'booking_id',
        'dm_display',
        'room_display',
        'script_display',
        'status',
        'is_locked',
        'scheduled_start_display',
        'player_count_display',
        'created_at',
    ]
    list_filter = [
        'status',
        'is_locked',
        ('dm_id', admin.RelatedOnlyFieldListFilter),
        ('room_id', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'booking_id',
        'dm_id',
        'room_id',
        'script_id',
    ]
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['status', 'is_locked']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('基本信息', {
            'fields': ('booking', 'dm', 'room', 'script')
        }),
        ('状态', {
            'fields': ('status', 'is_locked')
        }),
        ('时间', {
            'fields': ('actual_start_time', 'actual_end_time')
        }),
        ('系统字段', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def dm_display(self, obj):
        if not obj.dm_id:
            return '-'
        try:
            from django.apps import apps
            DMProfile = apps.get_model('accounts', 'DMProfile')
            dm = DMProfile.objects.filter(pk=obj.dm_id).select_related('user').first()
            if dm and dm.user:
                name = getattr(dm.user, 'name', '') or getattr(dm.user, 'username', '')
                return format_html(
                    '<span style="color: #2563EB;">{}</span>',
                    name or f'DM#{obj.dm_id}'
                )
        except LookupError:
            pass
        return f'DM#{obj.dm_id}'
    dm_display.short_description = 'DM'
    dm_display.admin_order_field = 'dm_id'

    def room_display(self, obj):
        if not obj.room_id:
            return '-'
        try:
            from django.apps import apps
            Room = apps.get_model('stores', 'Room')
            room = Room.objects.filter(pk=obj.room_id).first()
            if room:
                return format_html(
                    '<span style="color: #059669;">{}</span>',
                    room.name
                )
        except LookupError:
            pass
        return f'房间#{obj.room_id}'
    room_display.short_description = '房间'
    room_display.admin_order_field = 'room_id'

    def script_display(self, obj):
        if not obj.script_id:
            return '-'
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script = Script.objects.filter(pk=obj.script_id).first()
            if script:
                return format_html(
                    '<span style="color: #7C3AED;">{}</span>',
                    script.name
                )
        except LookupError:
            pass
        return f'剧本#{obj.script_id}'
    script_display.short_description = '剧本'
    script_display.admin_order_field = 'script_id'

    def scheduled_start_display(self, obj):
        dt = obj.scheduled_start_time
        if dt:
            color = '#6B7280'
            if obj.status == ScheduleStatus.IN_PROGRESS:
                color = '#F59E0B'
            elif obj.status == ScheduleStatus.COMPLETED:
                color = '#059669'
            elif obj.status == ScheduleStatus.CANCELLED:
                color = '#EF4444'
            return format_html(
                '<span style="color: {};">{}</span>',
                color,
                dt.strftime('%Y-%m-%d %H:%M')
            )
        return '-'
    scheduled_start_display.short_description = '计划时间'

    def player_count_display(self, obj):
        count = obj.player_count
        if count > 0:
            color = '#059669' if count <= 6 else '#F59E0B'
            return format_html(
                '<span style="color: {}; font-weight: bold;">{}人</span>',
                color, count
            )
        return '-'
    player_count_display.short_description = '人数'

    actions = ['lock_schedules', 'unlock_schedules', 'mark_confirmed']

    def lock_schedules(self, request, queryset):
        updated = queryset.update(is_locked=True)
        self.message_user(request, f'已锁定 {updated} 个排班')
    lock_schedules.short_description = '锁定选中的排班'

    def unlock_schedules(self, request, queryset):
        updated = queryset.update(is_locked=False)
        self.message_user(request, f'已解锁 {updated} 个排班')
    unlock_schedules.short_description = '解锁选中的排班'

    def mark_confirmed(self, request, queryset):
        updated = queryset.filter(
            status=ScheduleStatus.ASSIGNED
        ).update(status=ScheduleStatus.DM_CONFIRMED)
        self.message_user(request, f'已确认 {updated} 个排班')
    mark_confirmed.short_description = '标记为DM已确认'


@admin.register(ScheduleConflict)
class ScheduleConflictAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'schedule1_display',
        'conflict_type',
        'schedule2_display',
        'resolved',
        'description_short',
        'created_at',
    ]
    list_filter = [
        'conflict_type',
        'resolved',
        'created_at',
    ]
    search_fields = [
        'description',
        'schedule1_id',
        'schedule2_id',
    ]
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    list_editable = ['resolved']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('冲突信息', {
            'fields': ('schedule1', 'schedule2', 'conflict_type', 'description')
        }),
        ('状态', {
            'fields': ('resolved',)
        }),
        ('系统字段', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def schedule1_display(self, obj):
        return self._format_schedule_ref(obj.schedule1_id)
    schedule1_display.short_description = '排班1'

    def schedule2_display(self, obj):
        return self._format_schedule_ref(obj.schedule2_id)
    schedule2_display.short_description = '排班2'

    def _format_schedule_ref(self, schedule_id):
        if not schedule_id:
            return '-'
        try:
            sched = Schedule.objects.get(pk=schedule_id)
            status_color = {
                ScheduleStatus.ASSIGNED: '#3B82F6',
                ScheduleStatus.DM_CONFIRMED: '#10B981',
                ScheduleStatus.IN_PROGRESS: '#F59E0B',
                ScheduleStatus.COMPLETED: '#6B7280',
                ScheduleStatus.CANCELLED: '#EF4444',
            }
            color = status_color.get(sched.status, '#6B7280')
            return format_html(
                '<a href="/admin/scheduling/schedule/{}/change/" '
                'style="color: {}; font-weight: bold;">#{}</a>',
                schedule_id, color, schedule_id
            )
        except Schedule.DoesNotExist:
            return f'#{schedule_id}'

    def description_short(self, obj):
        desc = obj.description or ''
        if len(desc) > 50:
            return desc[:50] + '...'
        return desc
    description_short.short_description = '描述'

    actions = ['resolve_conflicts']

    def resolve_conflicts(self, request, queryset):
        updated = queryset.update(resolved=True)
        self.message_user(request, f'已解决 {updated} 个冲突')
    resolve_conflicts.short_description = '标记选中冲突为已解决'
