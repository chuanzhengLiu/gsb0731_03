from django.contrib import admin

from .models import (
    DMProfile,
    DMSkill,
    DMAvailability,
    DMTemporaryUnavailable,
)


@admin.register(DMProfile)
class DMProfileAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'user',
        'user_name',
        'user_role',
        'store',
        'join_date',
        'total_sessions',
        'avg_rating',
        'consecutive_days',
        'fatigue_warning',
        'created_at',
    ]
    list_display_links = ['id', 'user']
    list_filter = [
        'fatigue_warning',
        'join_date',
        'created_at',
    ]
    search_fields = [
        'user__username',
        'user__name',
        'user__phone',
    ]
    ordering = ['-created_at']
    readonly_fields = [
        'id',
        'created_at',
    ]
    raw_id_fields = ['user']

    fieldsets = (
        (None, {
            'fields': ('id', 'user', 'join_date')
        }),
        ('统计信息', {
            'fields': (
                'specialty_types',
                'total_sessions',
                'avg_rating',
            ),
        }),
        ('疲劳状态', {
            'fields': (
                'consecutive_days',
                'fatigue_warning',
            ),
        }),
        ('重要日期', {
            'fields': ('created_at',),
        }),
    )

    def user_name(self, obj):
        return obj.user.name
    user_name.short_description = '姓名'
    user_name.admin_order_field = 'user__name'

    def user_role(self, obj):
        return obj.user.get_role_display()
    user_role.short_description = '角色'

    def store(self, obj):
        if obj.user.store:
            return obj.user.store.name
        return '-'
    store.short_description = '所属门店'
    store.admin_order_field = 'user__store__name'

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('user', 'user__store')
        if request.user.is_superuser or request.user.role == 'platform_admin':
            return qs
        return qs.filter(user__store_id=request.user.store_id)


@admin.register(DMSkill)
class DMSkillAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'dm',
        'dm_name',
        'script',
        'script_type',
        'proficiency',
        'play_count',
        'last_played',
    ]
    list_display_links = ['id', 'dm']
    list_filter = [
        'proficiency',
        'script__type',
    ]
    search_fields = [
        'dm__user__username',
        'dm__user__name',
        'script__name',
    ]
    ordering = ['dm', '-proficiency', '-play_count']
    readonly_fields = ['id']
    raw_id_fields = ['dm', 'script']

    def dm_name(self, obj):
        return obj.dm.user.name
    dm_name.short_description = 'DM姓名'
    dm_name.admin_order_field = 'dm__user__name'

    def script_type(self, obj):
        return obj.script.get_type_display()
    script_type.short_description = '剧本类型'

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            'dm__user', 'dm__user__store', 'script'
        )
        if request.user.is_superuser or request.user.role == 'platform_admin':
            return qs
        return qs.filter(dm__user__store_id=request.user.store_id)


@admin.register(DMAvailability)
class DMAvailabilityAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'dm',
        'dm_name',
        'day_of_week',
        'get_day_display',
        'start_time',
        'end_time',
        'is_recurring',
        'specific_date',
        'is_unavailable',
        'note',
    ]
    list_display_links = ['id', 'dm']
    list_filter = [
        'day_of_week',
        'is_recurring',
        'is_unavailable',
        'specific_date',
    ]
    search_fields = [
        'dm__user__username',
        'dm__user__name',
        'note',
    ]
    ordering = ['dm', 'day_of_week', 'start_time']
    readonly_fields = ['id']
    raw_id_fields = ['dm']

    def dm_name(self, obj):
        return obj.dm.user.name
    dm_name.short_description = 'DM姓名'
    dm_name.admin_order_field = 'dm__user__name'

    def get_day_display(self, obj):
        return obj.get_day_of_week_display()
    get_day_display.short_description = '星期'

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('dm__user', 'dm__user__store')
        if request.user.is_superuser or request.user.role == 'platform_admin':
            return qs
        return qs.filter(dm__user__store_id=request.user.store_id)


@admin.register(DMTemporaryUnavailable)
class DMTemporaryUnavailableAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'dm',
        'dm_name',
        'start_date',
        'end_date',
        'reason',
        'is_approved',
        'created_at',
    ]
    list_display_links = ['id', 'dm']
    list_filter = [
        'is_approved',
        'start_date',
        'end_date',
        'created_at',
    ]
    search_fields = [
        'dm__user__username',
        'dm__user__name',
        'reason',
    ]
    ordering = ['-created_at']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['dm']

    actions = ['approve_selected']

    def dm_name(self, obj):
        return obj.dm.user.name
    dm_name.short_description = 'DM姓名'
    dm_name.admin_order_field = 'dm__user__name'

    def approve_selected(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'已批准 {updated} 条请假记录')
    approve_selected.short_description = '批准选中的请假记录'

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('dm__user', 'dm__user__store')
        if request.user.is_superuser or request.user.role == 'platform_admin':
            return qs
        return qs.filter(dm__user__store_id=request.user.store_id)
