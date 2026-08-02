from rest_framework import permissions


PLATFORM_ADMIN = 'platform_admin'
STORE_MANAGER = 'store_manager'
ASSISTANT_MANAGER = 'assistant_manager'
DM = 'dm'
FRONT_DESK = 'front_desk'
PLAYER = 'player'

BOOKING_MANAGE_ROLES = [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]
BOOKING_VIEW_ROLES = BOOKING_MANAGE_ROLES + [DM]


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


def _get_user_booking_ids(user):
    try:
        from apps.scheduling.models import Schedule
        schedules = Schedule.objects.filter(dm_id=user.id).values_list('booking_id', flat=True)
        return list(set(schedules))
    except Exception:
        return []


class BookingPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in BOOKING_VIEW_ROLES

        if view.action in [
            'create', 'update', 'partial_update', 'destroy',
            'confirm', 'cancel', 'complete', 'no_show',
            'recommend_scripts', 'available_dms', 'bulk_add_players'
        ]:
            return role in BOOKING_MANAGE_ROLES

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)

        if role == DM:
            if view.action in ['retrieve']:
                if user_store_id == obj.store_id:
                    allowed_booking_ids = _get_user_booking_ids(request.user)
                    return obj.id in allowed_booking_ids
            return False

        if role in BOOKING_MANAGE_ROLES:
            return user_store_id == obj.store_id

        return False


class BookingPlayerPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return role in BOOKING_VIEW_ROLES

        if view.action in ['create', 'update', 'partial_update', 'destroy', 'bulk_create']:
            return role in BOOKING_MANAGE_ROLES

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        booking_store_id = getattr(obj.booking, 'store_id', None)

        if role == DM:
            if view.action in ['retrieve']:
                if user_store_id == booking_store_id:
                    allowed_booking_ids = _get_user_booking_ids(request.user)
                    return obj.booking_id in allowed_booking_ids
            return False

        if role in BOOKING_MANAGE_ROLES:
            return user_store_id == booking_store_id

        return False
