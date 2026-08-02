from django.contrib import admin

from .models import PlayerProfile, RoleAssignment


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'phone',
        'name',
        'preference_tags_display',
        'horror_tolerance',
        'accept_reverse',
        'total_plays',
        'last_visit_date',
        'avg_satisfaction',
        'created_at',
    ]
    list_filter = [
        'horror_tolerance',
        'accept_reverse',
        'created_at',
    ]
    search_fields = [
        'phone',
        'name',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'total_plays',
        'last_visit_date',
        'avg_satisfaction',
    ]
    fieldsets = [
        (None, {
            'fields': [
                'phone',
                'name',
            ]
        }),
        ('偏好设置', {
            'fields': [
                'preference_tags',
                'horror_tolerance',
                'accept_reverse',
            ]
        }),
        ('历史记录', {
            'fields': [
                'history_roles',
                'total_plays',
                'last_visit_date',
                'avg_satisfaction',
            ]
        }),
        ('时间信息', {
            'fields': [
                'created_at',
                'updated_at',
            ]
        }),
    ]

    def preference_tags_display(self, obj):
        tags = obj.preference_tags or []
        if not tags:
            return '-'
        return '、'.join(tags)
    preference_tags_display.short_description = '偏好标签'

    def total_plays(self, obj):
        return obj.total_plays
    total_plays.short_description = '总场次'

    def last_visit_date(self, obj):
        return obj.last_visit_date
    last_visit_date.short_description = '最近到访'

    def avg_satisfaction(self, obj):
        return obj.avg_satisfaction
    avg_satisfaction.short_description = '平均满意度'


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'schedule_id',
        'player_name',
        'player_phone',
        'role_name',
        'script_name',
        'match_score',
        'is_manual_adjusted',
        'satisfaction',
        'assigned_at',
    ]
    list_filter = [
        'is_manual_adjusted',
        'assigned_at',
        'created_at',
    ]
    search_fields = [
        'player_name',
        'player_phone',
        'schedule_id',
    ]
    readonly_fields = [
        'assigned_at',
        'created_at',
    ]
    fieldsets = [
        (None, {
            'fields': [
                'schedule',
                'player_profile',
                'player_name',
                'player_phone',
                'role',
            ]
        }),
        ('匹配信息', {
            'fields': [
                'match_score',
                'is_manual_adjusted',
                'satisfaction',
            ]
        }),
        ('时间信息', {
            'fields': [
                'assigned_at',
                'created_at',
            ]
        }),
    ]

    def role_name(self, obj):
        return obj.role.name if obj.role else '-'
    role_name.short_description = '角色'

    def script_name(self, obj):
        if obj.role and obj.role.script:
            return obj.role.script.name
        return '-'
    script_name.short_description = '剧本'
