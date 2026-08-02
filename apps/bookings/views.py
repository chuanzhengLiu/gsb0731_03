from datetime import datetime, timedelta

from django.db.models import Case, Count, IntegerField, Q, When
from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Booking, BookingPlayer, BookingStatus
from .serializers import (
    AvailableDMQuerySerializer,
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


def _get_available_dms(store_id, date, start_time, duration_minutes, script_id=None,
                       exclude_booking_id=None):
    from django.apps import apps
    from apps.scheduling.models import Schedule
    from apps.scheduling.utils import turnaround_gap_if_too_close

    User = apps.get_model('accounts', 'User')

    start_dt = datetime.combine(date, start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    dms = User.objects.filter(
        role=UserRole.DM,
        store_id=store_id,
        is_active=True
    )

    busy_dm_ids = set()
    too_close_dm_gaps = {}

    # 一次查出相邻日期范围内本店所有排班，避免逐个 DM 查库；用 date±1 覆盖跨零点的相邻场次。
    # 注意：Schedule.dm 指向 dms.DMProfile，门店信息在其关联的 User 上（DMProfile.store_id 只是个 Python property，
    # 不能用于 ORM 过滤），所以按 dm__user__store_id 过滤，并用 dm.user_id 归一到 User 主键。
    conflicting_schedules = Schedule.objects.filter(
        dm__user__store_id=store_id,
        booking__date__range=(date - timedelta(days=1), date + timedelta(days=1)),
    ).select_related('booking', 'dm')

    for schedule in conflicting_schedules:
        booking = schedule.booking
        if not booking or not schedule.dm_id:
            continue
        if exclude_booking_id and booking.id == exclude_booking_id:
            continue
        if booking.status in [BookingStatus.CANCELLED, BookingStatus.NO_SHOW]:
            continue
        # 归一到 User 主键：可约列表是 User，排班外键是 DMProfile，两者主键不同，必须用 dm.user_id 对齐。
        dm_user_id = schedule.dm.user_id
        booking_start = datetime.combine(booking.date, booking.start_time)
        booking_end = booking_start + timedelta(minutes=booking.duration_minutes)
        if start_dt < booking_end and booking_start < end_dt:
            busy_dm_ids.add(dm_user_id)
            continue
        # 时间没撞，但间隔不足 MIN_TURNAROUND_MINUTES（含首尾相接的 0）也不放出来。
        gap = turnaround_gap_if_too_close(
            start_dt, end_dt, booking_start, booking_end
        )
        if gap is not None:
            prev = too_close_dm_gaps.get(dm_user_id)
            if prev is None or gap < prev:
                too_close_dm_gaps[dm_user_id] = gap

    # 撞单的 DM 不算"间隔太近"，避免重复出现在两份名单里
    for dm_id in busy_dm_ids:
        too_close_dm_gaps.pop(dm_id, None)

    dms = dms.exclude(id__in=busy_dm_ids | set(too_close_dm_gaps.keys()))

    dm_proficiency = {}
    if script_id:
        # 熟练度真实存在于 dms.DMSkill（字段 proficiency），经 DMProfile 关联到 User；
        # 原来引用的 DMScriptProficiency/proficiency_level 均不存在，这里按真实模型一次查出并归一到 User 主键。
        DMSkill = apps.get_model('dms', 'DMSkill')
        skills = DMSkill.objects.filter(
            dm__user__store_id=store_id,
            script_id=script_id,
        ).values('dm__user_id', 'proficiency')
        for skill in skills:
            dm_proficiency[skill['dm__user_id']] = skill['proficiency']

    return dms, dm_proficiency, too_close_dm_gaps


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

    @action(detail=False, methods=['get'], url_path='available-dms')
    def available_dms(self, request):
        query_serializer = AvailableDMQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        data = query_serializer.validated_data

        store_id = data['store_id']

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)
        if role != PLATFORM_ADMIN:
            if not user_store_id or user_store_id != store_id:
                return Response(
                    {'detail': '无权访问该门店的可约DM'},
                    status=status.HTTP_403_FORBIDDEN
                )
            if role not in BOOKING_MANAGE_ROLES:
                return Response(
                    {'detail': '无权访问此接口'},
                    status=status.HTTP_403_FORBIDDEN
                )

        dms, dm_proficiency, too_close_dm_gaps = _get_available_dms(
            store_id=store_id,
            date=data['date'],
            start_time=data['start_time'],
            duration_minutes=data.get('duration_minutes', 240),
            script_id=data.get('script_id'),
            exclude_booking_id=data.get('exclude_booking_id'),
        )

        available = [
            {
                'id': dm.id,
                'name': dm.name or dm.username,
                'proficiency': dm_proficiency.get(dm.id),
            }
            for dm in dms
        ]

        # 被间隔规则筛掉的 DM 不静默消失，带上名单和各自的间隔分钟数供前端解释
        excluded_ids = list(too_close_dm_gaps.keys())
        excluded_name_map = {}
        if excluded_ids:
            try:
                from django.apps import apps
                User = apps.get_model('accounts', 'User')
                for dm in User.objects.filter(id__in=excluded_ids):
                    excluded_name_map[dm.id] = dm.name or dm.username
            except Exception:
                pass
        too_close = [
            {
                'id': dm_id,
                'name': excluded_name_map.get(dm_id, ''),
                'gap_minutes': gap,
            }
            for dm_id, gap in too_close_dm_gaps.items()
        ]

        return Response({
            'available_dms': available,
            'too_close_dms': too_close,
        })

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
