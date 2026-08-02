from rest_framework import permissions

from apps.accounts.models import UserRole, ROLE_HIERARCHY


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER
DM_ROLE = UserRole.DM
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


def _get_user_id(user):
    return getattr(user, 'id', None)


def _get_dm_user_id(obj):
    dm_profile = getattr(obj, 'dm', None)
    if dm_profile is not None:
        user = getattr(dm_profile, 'user', None)
        if user is not None:
            return getattr(user, 'id', None)
    user = getattr(obj, 'user', None)
    if user is not None:
        return getattr(user, 'id', None)
    return None


def _get_dm_store_id(obj):
    dm_profile = getattr(obj, 'dm', None)
    if dm_profile is not None:
        user = getattr(dm_profile, 'user', None)
        if user is not None:
            store = getattr(user, 'store', None)
            if store is not None:
                return getattr(store, 'id', store)
    user = getattr(obj, 'user', None)
    if user is not None:
        store = getattr(user, 'store', None)
        if store is not None:
            return getattr(store, 'id', store)
    store = getattr(obj, 'store', None)
    if store is not None:
        return getattr(store, 'id', store)
    store_id = getattr(obj, 'store_id', None)
    return store_id


def _has_role_or_above(user, role):
    user_level = ROLE_HIERARCHY.get(_get_user_role(user), 0)
    required_level = ROLE_HIERARCHY.get(role, 999)
    return user_level >= required_level


class DMProfilePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE, FRONT_DESK]

        if view.action in ['create']:
            return role in [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER]

        if view.action in ['update', 'partial_update']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE]

        if view.action == 'destroy':
            return role in [PLATFORM_ADMIN, STORE_MANAGER]

        if view.action in ['workload', 'fatigue_warnings']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        obj_store_id = _get_dm_store_id(obj)
        obj_user_id = _get_dm_user_id(obj)
        current_user_id = _get_user_id(request.user)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        if view.action in ['update', 'partial_update']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        if view.action == 'destroy':
            if role == STORE_MANAGER:
                return user_store_id == obj_store_id

        if view.action in ['workload', 'fatigue_warnings']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        return False


class DMSkillPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE, FRONT_DESK]

        if view.action in ['create', 'update', 'partial_update', 'destroy', 'batch_update', 'set_skill']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        obj_store_id = _get_dm_store_id(obj)
        obj_user_id = _get_dm_user_id(obj)
        current_user_id = _get_user_id(request.user)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        if view.action in ['create', 'update', 'partial_update', 'destroy', 'set_skill']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        return False


class DMAvailabilityPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE, FRONT_DESK]

        if view.action in ['create', 'update', 'partial_update', 'destroy', 'batch_set']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        obj_store_id = _get_dm_store_id(obj)
        obj_user_id = _get_dm_user_id(obj)
        current_user_id = _get_user_id(request.user)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        if view.action in ['create', 'update', 'partial_update', 'destroy', 'batch_set']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        return False


class DMTemporaryUnavailablePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE, FRONT_DESK]

        if view.action in ['create']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE]

        if view.action in ['update', 'partial_update']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM_ROLE]

        if view.action == 'destroy':
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        if view.action == 'approve':
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        obj_store_id = _get_dm_store_id(obj)
        obj_user_id = _get_dm_user_id(obj)
        current_user_id = _get_user_id(request.user)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        if view.action in ['create', 'update', 'partial_update']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id
            if role == DM_ROLE:
                return current_user_id == obj_user_id

        if view.action == 'destroy':
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id

        if view.action == 'approve':
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj_store_id

        return False
