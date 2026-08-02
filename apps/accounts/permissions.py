from functools import wraps

from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

from .models import UserRole, ROLE_HIERARCHY


def require_role(role):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied('请先登录')
            if request.user.role != role:
                raise PermissionDenied(f'需要{UserRole(role).label}权限')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_role_or_above(role):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied('请先登录')
            required_level = ROLE_HIERARCHY.get(role, 999)
            user_level = ROLE_HIERARCHY.get(request.user.role, 0)
            if user_level < required_level:
                raise PermissionDenied(f'需要{UserRole(role).label}及以上权限')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def require_store_scoped(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied('请先登录')
        if not request.user.is_platform_admin() and request.user.store_id is None:
            raise PermissionDenied('您没有关联的门店')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


class IsPlatformAdmin(BasePermission):
    message = '需要平台管理员权限'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == UserRole.PLATFORM_ADMIN
        )


class IsStoreManager(BasePermission):
    message = '需要门店经理权限'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == UserRole.STORE_MANAGER
        )


class IsAssistantManagerOrAbove(BasePermission):
    message = '需要副经理及以上权限'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        required_level = ROLE_HIERARCHY.get(UserRole.ASSISTANT_MANAGER, 60)
        user_level = ROLE_HIERARCHY.get(request.user.role, 0)
        return user_level >= required_level


class IsDM(BasePermission):
    message = '需要DM权限'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == UserRole.DM
        )


class IsFrontDesk(BasePermission):
    message = '需要前台权限'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == UserRole.FRONT_DESK
        )


class IsPlayer(BasePermission):
    message = '需要玩家权限'

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == UserRole.PLAYER
        )


class StoreScopedPermission(BasePermission):
    message = '您无权访问其他门店的数据'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_platform_admin():
            return True
        if request.user.store_id is None:
            raise PermissionDenied('您没有关联的门店')
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_platform_admin():
            return True
        obj_store_id = getattr(obj, 'store_id', None)
        if obj_store_id is None:
            obj_store = getattr(obj, 'store', None)
            if obj_store is not None:
                obj_store_id = getattr(obj_store, 'id', None)
        return request.user.store_id == obj_store_id
