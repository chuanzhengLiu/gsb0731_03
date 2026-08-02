from rest_framework import permissions

from apps.accounts.models import UserRole


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER
DM = UserRole.DM
FRONT_DESK = UserRole.FRONT_DESK


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


def _get_dm_user_id(user):
    try:
        from django.apps import apps
        DMProfile = apps.get_model('accounts', 'DMProfile')
        dm_profile = DMProfile.objects.filter(user_id=user.id).first()
        return dm_profile.id if dm_profile else None
    except LookupError:
        return None


class IsPlatformAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return _get_user_role(request.user) == PLATFORM_ADMIN

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class SchedulePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve', 'calendar']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]

        if view.action in ['create', 'update', 'partial_update', 'destroy',
                           'lock', 'unlock', 'adjust', 'confirm_status']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        if view.action in ['run_scheduling', 'reassign']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        obj_store_id = obj.store_id

        if view.action in ['list', 'retrieve', 'calendar']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]:
                return user_store_id == obj_store_id
            if role == DM:
                dm_id = _get_dm_user_id(request.user)
                return (obj.dm_id == dm_id) or (user_store_id == obj_store_id)

        if view.action in ['create', 'update', 'partial_update', 'destroy',
                           'lock', 'unlock', 'adjust', 'confirm_status']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id

        return False


class SchedulingPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if request.method == 'POST':
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        return False


class ReassignmentPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if request.method == 'POST':
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        return False


class ConflictPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]

        if view.action in ['update', 'partial_update', 'mark_resolved']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)

        sched1_store = getattr(obj.schedule1, 'store_id', None)
        sched2_store = getattr(obj.schedule2, 'store_id', None)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]:
                return user_store_id in [sched1_store, sched2_store]
            if role == DM:
                dm_id = _get_dm_user_id(request.user)
                return (
                    obj.schedule1.dm_id == dm_id or
                    obj.schedule2.dm_id == dm_id or
                    user_store_id in [sched1_store, sched2_store]
                )

        if view.action in ['update', 'partial_update', 'mark_resolved']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id in [sched1_store, sched2_store]

        return False


class ScheduleCalendarPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if request.method == 'GET':
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]

        return False
