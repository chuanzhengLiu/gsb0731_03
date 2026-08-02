from django.contrib import admin
from django.utils.html import format_html

from .models import Review, ScriptStats


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'schedule_id',
        'script_display',
        'dm_display',
        'dm_rating_display',
        'script_rating_display',
        'player_review_status',
        'dm_review_status',
        'completed_by_display',
        'created_at',
    ]
    list_filter = [
        'dm_rating',
        'script_rating',
        'created_at',
    ]
    search_fields = [
        'schedule_id',
        'comment',
        'dm_tags',
        'script_tags',
    ]
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('基本信息', {
            'fields': ('schedule', 'completed_by')
        }),
        ('玩家评价', {
            'fields': (
                'dm_rating', 'script_rating',
                'dm_tags', 'script_tags',
                'comment',
            )
        }),
        ('DM复盘', {
            'fields': ('dm_review',)
        }),
        ('系统字段', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def _render_stars(self, rating):
        if not rating:
            return '-'
        full_stars = '★' * rating
        empty_stars = '☆' * (5 - rating)
        color_map = {
            5: '#059669',
            4: '#10B981',
            3: '#F59E0B',
            2: '#F97316',
            1: '#EF4444',
        }
        color = color_map.get(rating, '#6B7280')
        return format_html(
            '<span style="color: {}; font-size: 16px;">{}{}</span> <span style="color: #6B7280; margin-left: 4px;">({}星)</span>',
            color, full_stars, empty_stars, rating
        )

    def dm_rating_display(self, obj):
        return self._render_stars(obj.dm_rating)
    dm_rating_display.short_description = 'DM评分'
    dm_rating_display.admin_order_field = 'dm_rating'

    def script_rating_display(self, obj):
        return self._render_stars(obj.script_rating)
    script_rating_display.short_description = '剧本评分'
    script_rating_display.admin_order_field = 'script_rating'

    def script_display(self, obj):
        schedule = obj.schedule
        if not schedule or not schedule.script_id:
            return '-'
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script = Script.objects.filter(pk=schedule.script_id).first()
            if script:
                return format_html(
                    '<span style="color: #7C3AED;">{}</span>',
                    script.name
                )
        except LookupError:
            pass
        return f'剧本#{schedule.script_id}'
    script_display.short_description = '剧本'

    def dm_display(self, obj):
        schedule = obj.schedule
        if not schedule or not schedule.dm_id:
            return '-'
        try:
            from django.apps import apps
            DMProfile = apps.get_model('accounts', 'DMProfile')
            dm = DMProfile.objects.filter(pk=schedule.dm_id).select_related('user').first()
            if dm and dm.user:
                name = getattr(dm.user, 'name', '') or getattr(dm.user, 'username', '')
                return format_html(
                    '<span style="color: #2563EB;">{}</span>',
                    name or f'DM#{schedule.dm_id}'
                )
        except LookupError:
            pass
        return f'DM#{schedule.dm_id}'
    dm_display.short_description = 'DM'

    def player_review_status(self, obj):
        if obj.has_player_review:
            return format_html(
                '<span style="background: #059669; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">已评价</span>'
            )
        return format_html(
            '<span style="background: #9CA3AF; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">未评价</span>'
        )
    player_review_status.short_description = '玩家评价'

    def dm_review_status(self, obj):
        if obj.has_dm_review:
            return format_html(
                '<span style="background: #059669; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">已复盘</span>'
            )
        return format_html(
            '<span style="background: #9CA3AF; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">未复盘</span>'
        )
    dm_review_status.short_description = 'DM复盘'

    def completed_by_display(self, obj):
        if obj.completed_by_id:
            user = obj.completed_by
            name = getattr(user, 'name', '') or getattr(user, 'username', '')
            role = getattr(user, 'get_role_display', lambda: '')()
            return format_html(
                '{} <span style="color: #6B7280; font-size: 12px;">({})</span>',
                name, role
            )
        return '-'
    completed_by_display.short_description = '提交人'

    actions = ['recalculate_stats']

    def recalculate_stats(self, request, queryset):
        script_ids = set()
        for review in queryset.select_related('schedule'):
            if review.schedule and review.schedule.script_id:
                script_ids.add(review.schedule.script_id)
        from .models import ScriptStats
        updated = 0
        for script_id in script_ids:
            stats, created = ScriptStats.objects.get_or_create(script_id=script_id)
            stats.update_stats()
            updated += 1
        self.message_user(request, f'已重新计算 {updated} 个剧本的统计数据')
    recalculate_stats.short_description = '重新计算所选评价关联剧本的统计'


@admin.register(ScriptStats)
class ScriptStatsAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'script_display',
        'store_display',
        'avg_dm_rating_display',
        'avg_script_rating_display',
        'overall_rating_display',
        'total_sessions',
        'completed_sessions',
        'completion_rate_display',
        'turnover_rate',
        'complaint_count',
        'last_updated',
    ]
    list_filter = [
        'last_updated',
    ]
    search_fields = [
        'script_id',
    ]
    ordering = ['-turnover_rate', '-avg_script_rating']
    readonly_fields = ['last_updated']

    fieldsets = (
        ('基本信息', {
            'fields': ('script',)
        }),
        ('评分统计', {
            'fields': ('avg_dm_rating', 'avg_script_rating')
        }),
        ('场次统计', {
            'fields': (
                'total_sessions', 'completed_sessions',
                'completion_rate', 'turnover_rate',
                'complaint_count',
            )
        }),
        ('系统字段', {
            'fields': ('last_updated',),
            'classes': ('collapse',),
        }),
    )

    def script_display(self, obj):
        if not obj.script_id:
            return '-'
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script = Script.objects.filter(pk=obj.script_id).first()
            if script:
                script_type = script.get_type_display()
                return format_html(
                    '<div><span style="color: #7C3AED; font-weight: bold;">{}</span>'
                    '<br><span style="color: #6B7280; font-size: 12px;">{}</span></div>',
                    script.name, script_type
                )
        except LookupError:
            pass
        return f'剧本#{obj.script_id}'
    script_display.short_description = '剧本'

    def store_display(self, obj):
        if not obj.script_id:
            return '-'
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script = Script.objects.filter(pk=obj.script_id).select_related('store').first()
            if script and script.store:
                return format_html(
                    '<span style="color: #059669;">{}</span>',
                    script.store.name
                )
        except LookupError:
            pass
        return '-'
    store_display.short_description = '门店'

    def _render_rating(self, value):
        if not value or value <= 0:
            return '-'
        color_map = [
            (4.5, '#059669'),
            (4.0, '#10B981'),
            (3.5, '#F59E0B'),
            (3.0, '#F97316'),
            (0, '#EF4444'),
        ]
        color = '#6B7280'
        for threshold, c in color_map:
            if value >= threshold:
                color = c
                break
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.2f}</span>',
            color, value
        )

    def avg_dm_rating_display(self, obj):
        return self._render_rating(obj.avg_dm_rating)
    avg_dm_rating_display.short_description = 'DM均分'
    avg_dm_rating_display.admin_order_field = 'avg_dm_rating'

    def avg_script_rating_display(self, obj):
        return self._render_rating(obj.avg_script_rating)
    avg_script_rating_display.short_description = '剧本均分'
    avg_script_rating_display.admin_order_field = 'avg_script_rating'

    def overall_rating_display(self, obj):
        return self._render_rating(obj.overall_rating)
    overall_rating_display.short_description = '综合评分'

    def completion_rate_display(self, obj):
        if obj.total_sessions <= 0:
            return '-'
        color = '#059669' if obj.completion_rate >= 80 else (
            '#F59E0B' if obj.completion_rate >= 60 else '#EF4444'
        )
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color, obj.completion_rate
        )
    completion_rate_display.short_description = '完场率'
    completion_rate_display.admin_order_field = 'completion_rate'

    actions = ['refresh_all_stats']

    def refresh_all_stats(self, request, queryset):
        updated = 0
        for stats in queryset:
            stats.update_stats()
            updated += 1
        self.message_user(request, f'已刷新 {updated} 个剧本的统计数据')
    refresh_all_stats.short_description = '刷新所选剧本的统计数据'
