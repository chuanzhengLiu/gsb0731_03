from datetime import datetime, timedelta

from django.db.models import Case, Count, IntegerField, Q, When
from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Booking, BookingPlayer, BookingStatus
from .serializers import (
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    BookingPlayerBulkCreateSerializer,
    BookingPlayerCreateSerializer,
    BookingPlayerSerializer,
    BookingSerializer,
    BookingStatusUpdateSerializer,
    BookingWithScriptRecommendationSerializer,
    ScriptRecommendationQuerySerializer,
)
from .permissions import (
    BOOKING_MANAGE_ROLES,
    BOOKING_VIEW_ROLES,
    BookingPermission,
    BookingPlayerPermission,
    PLATFORM_ADMIN,
)
from .filters import BookingFilter
from apps.scripts.models import Script, ScriptStatus, ScriptDifficulty
from apps.scripts.serializers import ScriptListSerializer
from apps.accounts.models import UserRole


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


def _get_dm_booking_ids(user):
    try:
        from apps.scheduling.models import Schedule
        schedules = Schedule.objects.filter(dm_id=user.id).values_list('booking_id', flat=True)
        return list(set(schedules))
    except Exception:
        return []


def _get_available_dms(store_id, date, start_time, duration_minutes, script_id=None):
    from apps.dms.models import DMProfile
    from apps.scheduling.utils import get_dm_unavailabilities

    start_dt = datetime.combine(date, start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    dm_profiles = DMProfile.objects.filter(
        user__store_id=store_id,
        user__is_active=True,
    ).select_related('user')

    unavailabilities = get_dm_unavailabilities(
        start=start_dt,
        end=end_dt,
        store_id=store_id,
    )
    unavailable_dm_ids = set(unavailabilities.keys())

    available_profiles = dm_profiles.exclude(id__in=unavailable_dm_ids)

    dm_proficiency = {}
    if script_id:
        try:
            from apps.dms.models import DMSkill
            skills = DMSkill.objects.filter(
                dm__in=available_profiles,
                script_id=script_id,
            ).select_related('dm')
            for skill in skills:
                dm_proficiency[skill.dm_id] = skill.proficiency
        except Exception:
            pass

    return available_profiles, dm_proficiency, unavailabilities


def _get_script_recommendations(store_id, player_count, preferred_types=None,
                                 difficulty_preference=None, is_newbie=False,
                                 date=None, start_time=None, duration_minutes=None):
    queryset = Script.objects.filter(
        store_id=store_id,
        status=ScriptStatus.AVAILABLE,
        inventory__gt=0,
    ).select_related('store')

    queryset = queryset.filter(
        **{f'player_count__total': player_count}
    )

    if difficulty_preference is not None:
        diff_q = Q(difficulty=difficulty_preference)
        if is_newbie and difficulty_preference > ScriptDifficulty.EASY:
            diff_q |= Q(difficulty=ScriptDifficulty.EASY)
        queryset = queryset.filter(diff_q)
    elif is_newbie:
        queryset = queryset.filter(difficulty__lte=ScriptDifficulty.MEDIUM)

    annotations = {}
    order_by_fields = []

    if preferred_types:
        type_order = []
        for idx, ptype in enumerate(preferred_types):
            type_order.append(When(type=ptype, then=idx))
        annotations['type_priority'] = Case(
            *type_order,
            default=len(preferred_types),
            output_field=IntegerField()
        )
        order_by_fields.append('type_priority')

    if date and start_time and duration_minutes:
        script_ids = list(queryset.values_list('id', flat=True))
        dm_score_map = {}
        for script_id in script_ids:
            _, dm_proficiency, _ = _get_available_dms(
                store_id, date, start_time, duration_minutes, script_id
            )
            if dm_proficiency:
                avg_prof = sum(dm_proficiency.values()) / len(dm_proficiency)
            else:
                avg_prof = 0
            dm_score_map[script_id] = avg_prof

        if dm_score_map:
            dm_case = []
            for sid, score in dm_score_map.items():
                dm_case.append(When(id=sid, then=int(score * 10)))
            if dm_case:
                annotations['dm_score'] = Case(
                    *dm_case,
                    default=0,
                    output_field=IntegerField()
                )
                order_by_fields.insert(0, '-dm_score')

    if annotations:
        queryset = queryset.annotate(**annotations)

    if order_by_fields:
        order_by_fields.extend(['-created_at'])
        queryset = queryset.order_by(*order_by_fields)
    else:
        queryset = queryset.order_by('-created_at')

    return queryset


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.select_related(
        'store', 'created_by'
    ).prefetch_related('players').all()
    permission_classes = [IsAuthenticated, BookingPermission]
    filterset_class = BookingFilter
    search_fields = ['customer_name', 'customer_phone']
    ordering_fields = ['date', 'start_time', 'created_at', 'player_count']
    ordering = ['-date', '-start_time']

    def get_serializer_class(self):
        if self.action == 'list':
            return BookingListSerializer
        elif self.action == 'retrieve':
            return BookingDetailSerializer
        elif self.action == 'create':
            return BookingCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BookingCreateSerializer
        return BookingSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = _get_user_role(user)

        if role == PLATFORM_ADMIN:
            return qs

        user_store_id = _get_user_store_id(user)
        if not user_store_id:
            return qs.none()

        if role in BOOKING_MANAGE_ROLES:
            return qs.filter(store_id=user_store_id)

        if role == UserRole.DM:
            allowed_booking_ids = _get_dm_booking_ids(user)
            return qs.filter(id__in=allowed_booking_ids, store_id=user_store_id)

        return qs.none()

    def perform_create(self, serializer):
        serializer.save(
            status=BookingStatus.PENDING,
            created_by=self.request.user
        )

    @action(detail=False, methods=['get'], url_path='available-dms')
    def available_dms(self, request):
        store_id = request.query_params.get('store_id')
        date_str = request.query_params.get('date')
        start_time_str = request.query_params.get('start_time')
        duration_minutes = request.query_params.get('duration_minutes')
        script_id = request.query_params.get('script_id')

        if not all([store_id, date_str, start_time_str, duration_minutes]):
            return Response(
                {'detail': '缺少必要参数: store_id, date, start_time, duration_minutes'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            store_id = int(store_id)
            duration_minutes = int(duration_minutes)
            date_val = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_time_val = datetime.strptime(start_time_str, '%H:%M').time()
        except (ValueError, TypeError):
            return Response(
                {'detail': '参数格式错误'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if script_id:
            try:
                script_id = int(script_id)
            except (ValueError, TypeError):
                script_id = None

        user = request.user
        role = _get_user_role(user)
        user_store_id = _get_user_store_id(user)

        if role != PLATFORM_ADMIN:
            if not user_store_id or user_store_id != store_id:
                return Response(
                    {'detail': '无权访问该门店'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if role not in BOOKING_MANAGE_ROLES:
                return Response(
                    {'detail': '无权访问此接口'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        available_profiles, dm_proficiency, unavailabilities = _get_available_dms(
            store_id, date_val, start_time_val, duration_minutes, script_id,
        )

        available_list = []
        for profile in available_profiles:
            item = {
                'dm_id': profile.id,
                'name': getattr(profile.user, 'name', '') or getattr(profile.user, 'username', ''),
                'phone': getattr(profile.user, 'phone', ''),
                'avg_rating': profile.avg_rating,
                'total_sessions': profile.total_sessions,
                'specialty_types': profile.specialty_types,
            }
            if script_id and profile.id in dm_proficiency:
                item['proficiency'] = dm_proficiency[profile.id]
            available_list.append(item)

        unavailable_list = []
        for dm_id, info in unavailabilities.items():
            unavailable_list.append({
                'dm_id': dm_id,
                'conflict_schedule_id': info['schedule_id'],
                'gap_minutes': info['gap_minutes'],
                'reason': '时间冲突' if info['gap_minutes'] == 0 else f'与相邻场次间隔仅{info["gap_minutes"]}分钟',
            })

        from apps.scheduling.utils import MIN_SCHEDULE_GAP_MINUTES

        return Response({
            'available_dms': available_list,
            'unavailable_dms': unavailable_list,
            'min_gap_minutes': MIN_SCHEDULE_GAP_MINUTES,
        })

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        booking = self.get_object()
        serializer = BookingStatusUpdateSerializer(
            data=request.data,
            context={'instance': booking}
        )
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        if new_status != BookingStatus.CONFIRMED:
            return Response(
                {'detail': '该接口只能用于确认预约'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            booking.transition_to(BookingStatus.CONFIRMED)
        except ValidationError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(BookingDetailSerializer(booking).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        serializer = BookingStatusUpdateSerializer(
            data={'status': BookingStatus.CANCELLED},
            context={'instance': booking}
        )
        serializer.is_valid(raise_exception=True)

        try:
            booking.transition_to(BookingStatus.CANCELLED)
        except ValidationError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(BookingDetailSerializer(booking).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        booking = self.get_object()
        serializer = BookingStatusUpdateSerializer(
            data={'status': BookingStatus.COMPLETED},
            context={'instance': booking}
        )
        serializer.is_valid(raise_exception=True)

        try:
            booking.transition_to(BookingStatus.COMPLETED)
        except ValidationError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(BookingDetailSerializer(booking).data)

    @action(detail=True, methods=['post'])
    def no_show(self, request, pk=None):
        booking = self.get_object()
        serializer = BookingStatusUpdateSerializer(
            data={'status': BookingStatus.NO_SHOW},
            context={'instance': booking}
        )
        serializer.is_valid(raise_exception=True)

        try:
            booking.transition_to(BookingStatus.NO_SHOW)
        except ValidationError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(BookingDetailSerializer(booking).data)

    @action(detail=False, methods=['get'])
    def recommend_scripts(self, request):
        query_serializer = ScriptRecommendationQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        data = query_serializer.validated_data

        store_id = data['store_id']
        player_count = data['player_count']
        preferred_types = data.get('preferred_types')
        difficulty_preference = data.get('difficulty_preference')
        is_newbie = data.get('is_newbie', False)

        user = request.user
        role = _get_user_role(user)
        user_store_id = _get_user_store_id(user)

        if role != PLATFORM_ADMIN:
            if not user_store_id or user_store_id != store_id:
                return Response(
                    {'detail': '无权访问该门店的剧本推荐'},
                    status=status.HTTP_403_FORBIDDEN
                )
            if role not in BOOKING_MANAGE_ROLES:
                return Response(
                    {'detail': '无权访问此接口'},
                    status=status.HTTP_403_FORBIDDEN
                )

        queryset = _get_script_recommendations(
            store_id=store_id,
            player_count=player_count,
            preferred_types=list(preferred_types) if preferred_types else None,
            difficulty_preference=difficulty_preference,
            is_newbie=is_newbie,
            date=None,
            start_time=None,
            duration_minutes=None,
        )

        page = self.paginate_queryset(queryset[:50])
        if page is not None:
            serializer = ScriptListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ScriptListSerializer(queryset[:20], many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })

    @action(detail=True, methods=['get'])
    def recommend_scripts_for_booking(self, request, pk=None):
        booking = self.get_object()

        preferences = booking.preferences or {}
        preferred_types = preferences.get('preferred_types')
        difficulty_preference = preferences.get('difficulty_preference')
        is_newbie = preferences.get('is_newbie', False)

        queryset = _get_script_recommendations(
            store_id=booking.store_id,
            player_count=booking.player_count,
            preferred_types=preferred_types,
            difficulty_preference=difficulty_preference,
            is_newbie=is_newbie,
            date=booking.date,
            start_time=booking.start_time,
            duration_minutes=booking.duration_minutes,
        )

        serializer = ScriptListSerializer(queryset[:20], many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })

    @action(detail=False, methods=['post'])
    def create_with_recommendation(self, request):
        serializer = BookingWithScriptRecommendationSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        booking_data = serializer.validated_data['booking_data']
        recommendation_query = serializer.validated_data.get('recommendation_query')

        booking_serializer = BookingCreateSerializer(
            data=booking_data,
            context={'request': request}
        )
        booking_serializer.is_valid(raise_exception=True)
        booking = booking_serializer.save(
            status=BookingStatus.PENDING,
            created_by=request.user
        )

        recommendations = []
        if recommendation_query:
            prefs = recommendation_query
            queryset = _get_script_recommendations(
                store_id=prefs.get('store_id') or booking.store_id,
                player_count=prefs.get('player_count') or booking.player_count,
                preferred_types=list(prefs['preferred_types']) if prefs.get('preferred_types') else None,
                difficulty_preference=prefs.get('difficulty_preference'),
                is_newbie=prefs.get('is_newbie', False),
                date=booking.date,
                start_time=booking.start_time,
                duration_minutes=booking.duration_minutes,
            )
            recommendations = ScriptListSerializer(queryset[:10], many=True).data

        return Response({
            'booking': BookingDetailSerializer(booking).data,
            'recommended_scripts': recommendations,
        }, status=status.HTTP_201_CREATED)


class BookingPlayerViewSet(viewsets.ModelViewSet):
    queryset = BookingPlayer.objects.select_related('booking', 'booking__store').all()
    permission_classes = [IsAuthenticated, BookingPlayerPermission]
    search_fields = ['name', 'phone']
    ordering_fields = ['id', 'created_at']
    ordering = ['id']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BookingPlayerCreateSerializer
        return BookingPlayerSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = _get_user_role(user)

        if role == PLATFORM_ADMIN:
            return qs

        user_store_id = _get_user_store_id(user)
        if not user_store_id:
            return qs.none()

        if role in BOOKING_MANAGE_ROLES:
            return qs.filter(booking__store_id=user_store_id)

        if role == UserRole.DM:
            allowed_booking_ids = _get_dm_booking_ids(user)
            return qs.filter(
                booking_id__in=allowed_booking_ids,
                booking__store_id=user_store_id
            )

        return qs.none()

    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        serializer = BookingPlayerBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        players = serializer.save()

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)
        if role != PLATFORM_ADMIN:
            for player in players:
                if player.booking.store_id != user_store_id:
                    return Response(
                        {'detail': '无权向非本门店预约添加玩家'},
                        status=status.HTTP_403_FORBIDDEN
                    )

        return Response(
            BookingPlayerSerializer(players, many=True).data,
            status=status.HTTP_201_CREATED
        )
