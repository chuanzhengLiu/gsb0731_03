from rest_framework import permissions

from apps.accounts.models import UserRole


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER

AUDIT_VIEW_ROLES = [PLATFORM_ADMIN, STORE_MANAGER]


def _get_user_role(user):
    return getattr(user, 'role', None)


def _get_user_store_id(user):
    store = getattr(user, 'store', None)
    if store is None:
        return None
    store_id = getattr(store, 'id', None)
    if store_id is None:
        return store
    return store_id


class AuditLogPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if role in AUDIT_VIEW_ROLES:
            if view.action in ['list', 'retrieve']:
                return True
            if hasattr(view, 'action') and view.action == 'export':
                return True

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if role in AUDIT_VIEW_ROLES:
            user_store_id = _get_user_store_id(request.user)
            if user_store_id is None:
                return False

            obj_store_id = getattr(obj, 'store_id', None)
            if obj_store_id is None:
                return role == PLATFORM_ADMIN

            return user_store_id == obj_store_id

        return False


class AuditExportPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)
        return role in AUDIT_VIEW_ROLES
