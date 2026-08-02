from rest_framework import permissions

from apps.accounts.models import UserRole


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER
DM = UserRole.DM
FRONT_DESK = UserRole.FRONT_DESK
PLAYER = UserRole.PLAYER


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


def _get_dm_profile_id(user):
    try:
        from django.apps import apps
        DMProfile = apps.get_model('accounts', 'DMProfile')
        dm_profile = DMProfile.objects.filter(user_id=user.id).first()
        return dm_profile.id if dm_profile else None
    except LookupError:
        return None


def _is_store_staff(role):
    return role in [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER, FRONT_DESK]


def _can_view_all(role):
    return role in [PLATFORM_ADMIN, STORE_MANAGER, ASSISTANT_MANAGER]


class ReviewPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            if view.action in ['submit_player_review']:
                return True
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return _is_store_staff(role) or role == DM

        if view.action in ['create', 'update', 'partial_update', 'destroy']:
            return _can_view_all(role)

        if view.action in ['submit_player_review']:
            return True

        if view.action in ['submit_dm_review']:
            return role == DM or _can_view_all(role)

        if view.action in ['refresh_stats']:
            return _can_view_all(role)

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        obj_store_id = obj.store_id

        if view.action in ['retrieve']:
            if _is_store_staff(role):
                return user_store_id == obj_store_id
            if role == DM:
                dm_profile_id = _get_dm_profile_id(request.user)
                schedule = getattr(obj, 'schedule', None)
                schedule_dm_id = getattr(schedule, 'dm_id', None) if schedule else None
                return (schedule_dm_id == dm_profile_id) or (user_store_id == obj_store_id)

        if view.action in ['update', 'partial_update', 'destroy']:
            if _can_view_all(role):
                return user_store_id == obj_store_id

        if view.action in ['submit_dm_review']:
            if role == DM:
                dm_profile_id = _get_dm_profile_id(request.user)
                schedule = getattr(obj, 'schedule', None)
                schedule_dm_id = getattr(schedule, 'dm_id', None) if schedule else None
                return schedule_dm_id == dm_profile_id
            if _can_view_all(role):
                return user_store_id == obj_store_id

        return False


class PlayerReviewSubmissionPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        phone = request.data.get('phone')
        if not phone:
            return False
        schedule = getattr(obj, 'schedule', None)
        if not schedule or not schedule.booking_id:
            return False
        try:
            from django.apps import apps
            Booking = apps.get_model('bookings', 'Booking')
            booking = Booking.objects.filter(pk=schedule.booking_id).first()
            if not booking:
                return False
            player_phones = list(booking.players.all().values_list('phone', flat=True))
            customer_phone = getattr(booking, 'customer_phone', None)
            valid_phones = [p for p in player_phones if p]
            if customer_phone:
                valid_phones.append(customer_phone)
            return phone in valid_phones
        except LookupError:
            return False


class DMReviewSubmissionPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        role = _get_user_role(request.user)
        return role == DM or _can_view_all(role)

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)
        if _can_view_all(role):
            user_store_id = _get_user_store_id(request.user)
            return user_store_id == obj.store_id
        if role == DM:
            dm_profile_id = _get_dm_profile_id(request.user)
            schedule = getattr(obj, 'schedule', None)
            schedule_dm_id = getattr(schedule, 'dm_id', None) if schedule else None
            return schedule_dm_id == dm_profile_id
        return False


class ScriptStatsPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        if view.action in ['list', 'retrieve']:
            return _is_store_staff(role) or role == DM

        if view.action in ['refresh_stats']:
            return _can_view_all(role)

        if view.action in ['create', 'update', 'partial_update', 'destroy']:
            return role == PLATFORM_ADMIN

        return False

    def has_object_permission(self, request, view, obj):
        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        user_store_id = _get_user_store_id(request.user)
        script_store_id = None
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                script_store_id = script.store_id if script else None
            except LookupError:
                pass

        if view.action in ['retrieve']:
            if _is_store_staff(role) or role == DM:
                return user_store_id == script_store_id

        if view.action in ['refresh_stats']:
            if _can_view_all(role):
                return user_store_id == script_store_id

        return False


class DashboardPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        role = _get_user_role(request.user)

        if role == PLATFORM_ADMIN:
            return True

        return _can_view_all(role)
