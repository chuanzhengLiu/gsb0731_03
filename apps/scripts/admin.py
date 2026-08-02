from django.contrib import admin
from .models import Script, Role


class RoleInline(admin.TabularInline):
    model = Role
    extra = 0
    fields = ('name', 'suggested_gender', 'personality_tags', 'description')


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'store',
        'type',
        'display_player_count',
        'duration_minutes',
        'difficulty',
        'status',
        'inventory',
        'created_at',
    )
    list_filter = (
        'type',
        'difficulty',
        'status',
        'store',
        'created_at',
    )
    search_fields = ('name', 'description')
    inlines = [RoleInline]
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 50

    def display_player_count(self, obj):
        pc = obj.player_count
        if isinstance(pc, dict):
            total = pc.get('total', 0)
            male = pc.get('male', 0)
            female = pc.get('female', 0)
            return f'{total}人 (男{male}/女{female})'
        return '-'
    display_player_count.short_description = '玩家人数'


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'script',
        'suggested_gender',
        'display_tags',
    )
    list_filter = (
        'suggested_gender',
        'script__store',
        'script__type',
    )
    search_fields = ('name', 'description', 'script__name')
    list_per_page = 50

    def display_tags(self, obj):
        if isinstance(obj.personality_tags, list):
            return '、'.join(obj.personality_tags)
        return '-'
    display_tags.short_description = '性格标签'
