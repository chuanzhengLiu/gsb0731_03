from django.contrib import admin

from .models import Store, Room


class RoomInline(admin.TabularInline):
    model = Room
    extra = 1
    fields = ['name', 'capacity', 'has_props', 'is_active']


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'address', 'admin', 'created_at']
    list_display_links = ['id', 'name']
    search_fields = ['name', 'address']
    list_filter = ['created_at']
    readonly_fields = ['created_at']
    inlines = [RoomInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'store', 'name', 'capacity', 'has_props', 'is_active', 'created_at']
    list_display_links = ['id', 'name']
    search_fields = ['name', 'store__name']
    list_filter = ['store', 'has_props', 'is_active', 'created_at']
    readonly_fields = ['created_at']
    autocomplete_fields = ['store']
