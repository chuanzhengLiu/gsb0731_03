from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User, UserRole


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        'id',
        'username',
        'name',
        'role',
        'get_role_display',
        'store',
        'phone',
        'is_active',
        'first_login',
        'created_at',
        'last_login',
    ]
    list_display_links = ['id', 'username']
    list_filter = [
        'role',
        'is_active',
        'first_login',
        'store',
        'created_at',
    ]
    search_fields = [
        'username',
        'name',
        'phone',
    ]
    ordering = ['-created_at']
    readonly_fields = [
        'id',
        'created_at',
        'last_login',
    ]

    fieldsets = (
        (None, {
            'fields': ('id', 'username', 'password')
        }),
        (_('个人信息'), {
            'fields': ('name', 'phone')
        }),
        (_('权限信息'), {
            'fields': (
                'role',
                'store',
                'is_active',
                'first_login',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            ),
        }),
        (_('重要日期'), {
            'fields': ('created_at', 'last_login'),
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username',
                'password1',
                'password2',
                'name',
                'role',
                'store',
                'phone',
                'is_active',
                'is_staff',
                'is_superuser',
            ),
        }),
    )

    def get_role_display(self, obj):
        return obj.get_role_display()
    get_role_display.short_description = _('角色名称')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.role == UserRole.PLATFORM_ADMIN:
            return qs
        return qs.filter(store_id=request.user.store_id)
