from rest_framework import permissions


PLATFORM_ADMIN = 'PLATFORM_ADMIN'
STORE_MANAGER = 'STORE_MANAGER'
ASSISTANT_MANAGER = 'ASSISTANT_MANAGER'
DM = 'DM'
FRONT_DESK = 'FRONT_DESK'


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


class IsPlatformAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return _get_user_role(request.user) == PLATFORM_ADMIN

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class StorePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]

        if view.action in ['update', 'partial_update']:
            return role in [STORE_MANAGER]

        if view.action == 'create':
            return role == PLATFORM_ADMIN

        if view.action == 'destroy':
            return role == PLATFORM_ADMIN

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]:
                return user_store_id == obj.id

        if view.action in ['update', 'partial_update']:
            if role == STORE_MANAGER:
                return user_store_id == obj.id

        if view.action == 'destroy':
            return role == PLATFORM_ADMIN

        return False


class RoomPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]

        if view.action in ['create', 'update', 'partial_update', 'destroy']:
            return role in [STORE_MANAGER, ASSISTANT_MANAGER]

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)

        if view.action in ['list', 'retrieve']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER, DM, FRONT_DESK]:
                return user_store_id == obj.store_id

        if view.action in ['create', 'update', 'partial_update', 'destroy']:
            if role in [STORE_MANAGER, ASSISTANT_MANAGER]:
                return user_store_id == obj.store_id

        return False
