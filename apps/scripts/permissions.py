from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS


class IsStoreAdminOrStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return True
        return hasattr(request.user, 'store') and request.user.store is not None

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff or request.user.is_superuser:
            return True
        if hasattr(request.user, 'store') and request.user.store is not None:
            if hasattr(obj, 'store_id'):
                return obj.store_id == request.user.store_id
            if hasattr(obj, 'script'):
                return obj.script.store_id == request.user.store_id
        return False


class ScriptPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_staff or request.user.is_superuser:
            return True
        return hasattr(request.user, 'store') and request.user.store is not None

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_staff or request.user.is_superuser:
            return True
        if hasattr(request.user, 'store') and request.user.store is not None:
            return obj.store_id == request.user.store_id
        return False


class RolePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_staff or request.user.is_superuser:
            return True
        return hasattr(request.user, 'store') and request.user.store is not None

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_staff or request.user.is_superuser:
            return True
        if hasattr(request.user, 'store') and request.user.store is not None:
            return obj.script.store_id == request.user.store_id
        return False
