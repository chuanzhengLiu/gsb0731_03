from rest_framework import permissions

from apps.accounts.models import UserRole


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER
DM = UserRole.DM
FRONT_DESK = UserRole.FRONT_DESK
PLAYER = UserRole.PLAYER


PLAYER_PROFILE_MANAGE_ROLES = [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK, DM]
PLAYER_PROFILE_VIEW_ROLES = PLAYER_PROFILE_MANAGE_ROLES

ROLE_ASSIGNMENT_MANAGE_ROLES = [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK, DM]
ROLE_ASSIGNMENT_VIEW_ROLES = ROLE_ASSIGNMENT_MANAGE_ROLES

MATCH_ALGORITHM_ROLES = [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK, DM]


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


def _get_user_phone(user):
    return getattr(user, 'phone', None)


def _get_schedule_store_id(schedule):
    if schedule is None:
        return None
    try:
        from django.apps import apps
        Room = apps.get_model('stores', 'Room')
        if schedule.room_id:
            try:
                room = Room.objects.get(id=schedule.room_id)
                return room.store_id
            except Room.DoesNotExist:
                pass
    except LookupError:
        pass
    return None


class PlayerProfilePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve', 'lookup_by_phone']:
            return role in PLAYER_PROFILE_VIEW_ROLES

        if view.action in [
            'create', 'update', 'partial_update', 'destroy',
            'submit_preference',
        ]:
            return role in PLAYER_PROFILE_MANAGE_ROLES

        if view.action == 'history':
            if role == PLAYER:
                return True
            return role in PLAYER_PROFILE_VIEW_ROLES

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if role == PLAYER:
            if view.action in ['retrieve', 'history']:
                user_phone = _get_user_phone(request.user)
                if user_phone and obj.phone and user_phone == obj.phone:
                    return True
                if request.user.id and hasattr(obj, 'user_id'):
                    return request.user.id == obj.user_id
            return False

        return role in PLAYER_PROFILE_MANAGE_ROLES


class RoleAssignmentPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in ROLE_ASSIGNMENT_VIEW_ROLES

        if view.action in [
            'create', 'update', 'partial_update', 'destroy',
            'batch_create', 'update_satisfaction',
        ]:
            return role in ROLE_ASSIGNMENT_MANAGE_ROLES

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        if user_store_id is None:
            return False

        schedule = getattr(obj, 'schedule', None)
        schedule_store_id = _get_schedule_store_id(schedule)

        return schedule_store_id is not None and user_store_id == schedule_store_id


class RoleMatchPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if request.method == 'POST':
            return role in MATCH_ALGORITHM_ROLES

        return False


class PlayerHistoryPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if role == PLAYER:
            return True

        return role in PLAYER_PROFILE_VIEW_ROLES

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if role == PLAYER:
            user_phone = _get_user_phone(request.user)
            if user_phone and obj.phone and user_phone == obj.phone:
                return True
            return False

        return role in PLAYER_PROFILE_VIEW_ROLES
