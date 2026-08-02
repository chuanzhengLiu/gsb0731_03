from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Any, Optional

from django.db import models as django_models, transaction
from django.db.models import Avg, Count, Q, Sum, FloatField, Case, When, Value, IntegerField
from django.db.models.functions import TruncDate, ExtractWeekDay, ExtractHour
from django.utils import timezone
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import UserRole

from .models import Review, ScriptStats
from .serializers import (
    ReviewSerializer,
    ReviewCreateSerializer,
    ReviewDetailSerializer,
    PlayerReviewSerializer,
    DMReviewSerializer,
    ScriptStatsSerializer,
    ScriptStatsListSerializer,
)
from .permissions import (
    ReviewPermission,
    ScriptStatsPermission,
    DashboardPermission,
    _get_user_role,
    _get_user_store_id,
    _get_dm_profile_id,
    _can_view_all,
)
from .filters import ReviewFilter, ScriptStatsFilter

logger = logging.getLogger(__name__)


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER
DM = UserRole.DM
FRONT_DESK = UserRole.FRONT_DESK

DEFAULT_SCRIPT_PRICE = 500

TIME_SLOTS = [
    ('morning(9-12)', 9, 12),
    ('afternoon(12-18)', 12, 18),
    ('evening(18-22)', 18, 22),
    ('late_night(22-24)', 22, 24),
]


def _get_time_slot(hour):
    for slot_name, start, end in TIME_SLOTS:
        if start <= hour < end:
            return slot_name
    return None


def _get_schedule_store_ids(user):
    role = _get_user_role(user)
    if role == PLATFORM_ADMIN:
        return None
    user_store_id = _get_user_store_id(user)
    if not user_store_id:
        return []
    try:
        from django.apps import apps
        Room = apps.get_model('stores', 'Room')
        return list(Room.objects.filter(store_id=user_store_id).values_list('id', flat=True))
    except LookupError:
        return []


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.select_related(
        'schedule', 'completed_by'
    ).prefetch_related(
        'schedule__dm', 'schedule__script', 'schedule__room'
    ).all()
    permission_classes = [ReviewPermission]
    filterset_class = ReviewFilter
    search_fields = ['comment', 'schedule_id']
    ordering_fields = ['created_at', 'updated_at', 'dm_rating', 'script_rating']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)

        if role == PLATFORM_ADMIN:
            return qs

        user_store_id = _get_user_store_id(self.request.user)
        if not user_store_id:
            return qs.none()

        try:
            from django.apps import apps
            Room = apps.get_model('stores', 'Room')
            room_ids = Room.objects.filter(store_id=user_store_id).values_list('id', flat=True)
            from django.apps import apps
            Schedule = apps.get_model('scheduling', 'Schedule')
            schedule_ids = Schedule.objects.filter(room_id__in=room_ids).values_list('id', flat=True)
            store_reviews = qs.filter(schedule_id__in=schedule_ids)
        except LookupError:
            store_reviews = qs.none()

        if role == DM:
            dm_profile_id = _get_dm_profile_id(self.request.user)
            if dm_profile_id:
                try:
                    from django.apps import apps
                    Schedule = apps.get_model('scheduling', 'Schedule')
                    dm_schedule_ids = Schedule.objects.filter(
                        dm_id=dm_profile_id
                    ).values_list('id', flat=True)
                    dm_reviews = qs.filter(schedule_id__in=dm_schedule_ids)
                    qs = store_reviews | dm_reviews
                    qs = qs.distinct()
                    return qs
                except LookupError:
                    pass

        return store_reviews

    def get_serializer_class(self):
        if self.action == 'list':
            return ReviewSerializer
        if self.action == 'retrieve':
            return ReviewDetailSerializer
        if self.action == 'create':
            return ReviewCreateSerializer
        if self.action in ['update', 'partial_update']:
            return ReviewSerializer
        if self.action == 'submit_player_review':
            return PlayerReviewSerializer
        if self.action == 'submit_dm_review':
            return DMReviewSerializer
        return ReviewSerializer

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(completed_by=user)
        self._update_script_stats_for_schedule(serializer.instance.schedule_id)

    def perform_update(self, serializer):
        instance = serializer.save()
        if self.request.user.is_authenticated and not instance.completed_by_id:
            instance.completed_by = self.request.user
            instance.save()
        self._update_script_stats_for_schedule(instance.schedule_id)

    def perform_destroy(self, instance):
        schedule_id = instance.schedule_id
        instance.delete()
        self._update_script_stats_for_schedule(schedule_id)

    def _update_script_stats_for_schedule(self, schedule_id):
        if not schedule_id:
            return
        try:
            from django.apps import apps
            Schedule = apps.get_model('scheduling', 'Schedule')
            schedule = Schedule.objects.filter(pk=schedule_id).first()
            if schedule and schedule.script_id:
                stats, created = ScriptStats.objects.get_or_create(script_id=schedule.script_id)
                stats.update_stats()
        except Exception as e:
            logger.error(f'更新剧本统计失败: {e}', exc_info=True)

    @action(
        detail=True,
        methods=['post'],
        url_path='submit-player-review',
        permission_classes=[AllowAny],
    )
    def submit_player_review(self, request, pk=None):
        review = self.get_object()
        schedule_id = request.data.get('schedule') or review.schedule_id

        data = request.data.copy()
        if 'schedule' not in data:
            data['schedule'] = schedule_id

        serializer = PlayerReviewSerializer(
            review,
            data=data,
            partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            review = serializer.save()
            if request.user.is_authenticated and not review.completed_by_id:
                review.completed_by = request.user
                review.save()
            self._update_script_stats_for_schedule(review.schedule_id)

        return Response(ReviewDetailSerializer(review).data)

    @action(
        detail=True,
        methods=['post'],
        url_path='submit-dm-review',
    )
    def submit_dm_review(self, request, pk=None):
        review = self.get_object()
        schedule_id = request.data.get('schedule') or review.schedule_id

        data = request.data.copy()
        if 'schedule' not in data:
            data['schedule'] = schedule_id

        serializer = DMReviewSerializer(
            review,
            data=data,
            partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            review = serializer.save()
            if request.user.is_authenticated and not review.completed_by_id:
                review.completed_by = request.user
                review.save()
            self._update_script_stats_for_schedule(review.schedule_id)

        return Response(ReviewDetailSerializer(review).data)

    @action(
        detail=False,
        methods=['post'],
        url_path='create-or-get',
    )
    def create_or_get(self, request):
        schedule_id = request.data.get('schedule_id')
        if not schedule_id:
            return Response(
                {'detail': '请提供schedule_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from django.apps import apps
            Schedule = apps.get_model('scheduling', 'Schedule')
            schedule = Schedule.objects.filter(pk=schedule_id).first()
            if not schedule:
                return Response(
                    {'detail': '排班不存在'},
                    status=status.HTTP_404_NOT_FOUND,
                )
        except LookupError:
            return Response(
                {'detail': '系统错误'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        review, created = Review.objects.get_or_create(
            schedule_id=schedule_id,
            defaults={'completed_by': request.user if request.user.is_authenticated else None},
        )

        serializer = ReviewDetailSerializer(review)
        return Response({
            'created': created,
            'review': serializer.data,
        })


class ScriptStatsViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    GenericViewSet,
):
    queryset = ScriptStats.objects.select_related('script').all()
    permission_classes = [ScriptStatsPermission]
    filterset_class = ScriptStatsFilter
    search_fields = ['script_id']
    ordering_fields = [
        'avg_dm_rating', 'avg_script_rating',
        'total_sessions', 'completed_sessions',
        'completion_rate', 'turnover_rate',
        'complaint_count', 'last_updated',
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)

        if role == PLATFORM_ADMIN:
            return qs

        user_store_id = _get_user_store_id(self.request.user)
        if not user_store_id:
            return qs.none()

        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script_ids = Script.objects.filter(
                store_id=user_store_id
            ).values_list('id', flat=True)
            qs = qs.filter(script_id__in=script_ids)
        except LookupError:
            pass

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ScriptStatsListSerializer
        if self.action == 'retrieve':
            return ScriptStatsListSerializer
        return ScriptStatsSerializer

    @action(
        detail=True,
        methods=['post'],
        url_path='refresh-stats',
    )
    def refresh_stats(self, request, pk=None):
        stats = self.get_object()
        try:
            stats.update_stats()
            return Response(ScriptStatsListSerializer(stats).data)
        except Exception as e:
            logger.error(f'刷新剧本统计失败: {e}', exc_info=True)
            return Response(
                {'detail': f'刷新失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=['post'],
        url_path='refresh-all',
    )
    def refresh_all(self, request):
        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)

        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script_qs = Script.objects.all()
            if role != PLATFORM_ADMIN and user_store_id:
                script_qs = script_qs.filter(store_id=user_store_id)
            script_ids = list(script_qs.values_list('id', flat=True))
        except LookupError:
            script_ids = list(ScriptStats.objects.all().values_list('script_id', flat=True))

        updated = 0
        errors = []
        for script_id in script_ids:
            try:
                stats, created = ScriptStats.objects.get_or_create(script_id=script_id)
                stats.update_stats()
                updated += 1
            except Exception as e:
                errors.append(f'script#{script_id}: {str(e)}')

        return Response({
            'updated_count': updated,
            'total_count': len(script_ids),
            'errors': errors if errors else None,
        })

    @action(
        detail=False,
        methods=['get'],
        url_path='top-rated',
    )
    def top_rated(self, request):
        limit = int(request.query_params.get('limit', 10))
        qs = self.get_queryset().order_by(
            '-avg_script_rating', '-turnover_rate'
        )[:limit]
        serializer = ScriptStatsListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=['get'],
        url_path='top-turnover',
    )
    def top_turnover(self, request):
        limit = int(request.query_params.get('limit', 10))
        qs = self.get_queryset().order_by(
            '-turnover_rate', '-avg_script_rating'
        )[:limit]
        serializer = ScriptStatsListSerializer(qs, many=True)
        return Response(serializer.data)


class DashboardView(APIView):
    permission_classes = [DashboardPermission]

    def get(self, request):
        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)

        store_id = request.query_params.get('store_id')
        if store_id:
            store_id = int(store_id)
            if role != PLATFORM_ADMIN and store_id != user_store_id:
                return Response(
                    {'detail': '无权查看该门店数据'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:
            if role != PLATFORM_ADMIN:
                store_id = user_store_id

        months_back = int(request.query_params.get('months', 1))

        revenue_trend = self._get_revenue_trend(store_id, months_back)
        dm_ranking = self._get_dm_ranking(store_id, months_back)
        time_slot_analysis = self._get_time_slot_analysis(store_id, months_back)
        script_turnover = self._get_script_turnover(store_id)

        return Response({
            'revenue_trend': revenue_trend,
            'dm_ranking': dm_ranking,
            'time_slot_analysis': time_slot_analysis,
            'script_turnover': script_turnover,
        })

    def _get_store_filtered_schedules(self, store_id, months_back):
        try:
            from django.apps import apps
            Schedule = apps.get_model('scheduling', 'Schedule')
            ScheduleStatus = apps.get_model('scheduling', 'ScheduleStatus')
        except LookupError:
            return Schedule.objects.none()

        qs = Schedule.objects.select_related('script', 'dm').all()

        if store_id:
            try:
                from django.apps import apps
                Room = apps.get_model('stores', 'Room')
                room_ids = Room.objects.filter(store_id=store_id).values_list('id', flat=True)
                qs = qs.filter(room_id__in=room_ids)
            except LookupError:
                pass

        start_date = timezone.now().date() - timedelta(days=30 * months_back)
        try:
            from django.apps import apps
            Booking = apps.get_model('bookings', 'Booking')
            booking_ids = Booking.objects.filter(
                scheduled_start__date__gte=start_date
            ).values_list('id', flat=True)
            qs = qs.filter(booking_id__in=booking_ids)
        except LookupError:
            qs = qs.filter(created_at__gte=start_date)

        return qs

    def _get_revenue_trend(self, store_id, months_back):
        schedules = self._get_store_filtered_schedules(store_id, months_back)

        try:
            from django.apps import apps
            Booking = apps.get_model('bookings', 'Booking')
            bookings = Booking.objects.filter(
                id__in=schedules.values_list('booking_id', flat=True)
            )
            date_bookings = {}
            for booking in bookings:
                d = booking.scheduled_start.date()
                if d not in date_bookings:
                    date_bookings[d] = []
                date_bookings[d].append(booking.id)
        except LookupError:
            date_bookings = {}

        script_prices = {}
        schedule_script_map = {}
        for sched in schedules:
            schedule_script_map[sched.id] = sched.script_id
            if sched.script_id and sched.script_id not in script_prices:
                price = getattr(sched.script, 'price', None)
                if price is None:
                    try:
                        from django.apps import apps
                        Script = apps.get_model('scripts', 'Script')
                        script = Script.objects.filter(pk=sched.script_id).first()
                        price = getattr(script, 'price', DEFAULT_SCRIPT_PRICE)
                    except LookupError:
                        price = DEFAULT_SCRIPT_PRICE
                script_prices[sched.script_id] = price or DEFAULT_SCRIPT_PRICE

        daily_data = {}
        for d, booking_ids in date_bookings.items():
            day_schedules = schedules.filter(booking_id__in=booking_ids)
            count = day_schedules.count()
            amount = 0
            for sched in day_schedules:
                script_id = schedule_script_map.get(sched.id)
                amount += script_prices.get(script_id, DEFAULT_SCRIPT_PRICE)

            daily_data[d.isoformat()] = {
                'date': d.isoformat(),
                'amount': amount,
                'session_count': count,
            }

        start_date = timezone.now().date() - timedelta(days=30 * months_back)
        end_date = timezone.now().date()
        all_dates = []
        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            if date_str in daily_data:
                all_dates.append(daily_data[date_str])
            else:
                all_dates.append({
                    'date': date_str,
                    'amount': 0,
                    'session_count': 0,
                })
            current += timedelta(days=1)

        return sorted(all_dates, key=lambda x: x['date'])

    def _get_dm_ranking(self, store_id, months_back):
        schedules = self._get_store_filtered_schedules(store_id, months_back)

        dm_stats = {}
        for sched in schedules:
            if not sched.dm_id:
                continue
            if sched.dm_id not in dm_stats:
                dm_stats[sched.dm_id] = {
                    'dm_id': sched.dm_id,
                    'dm_name': '',
                    'sessions': 0,
                    'ratings': [],
                }
            dm_stats[sched.dm_id]['sessions'] += 1

            try:
                review = Review.objects.filter(schedule_id=sched.id).first()
                if review and review.dm_rating:
                    dm_stats[sched.dm_id]['ratings'].append(review.dm_rating)
            except Exception:
                pass

        try:
            from django.apps import apps
            DMProfile = apps.get_model('accounts', 'DMProfile')
            for dm_profile in DMProfile.objects.filter(
                id__in=dm_stats.keys()
            ).select_related('user'):
                if dm_profile.id in dm_stats and dm_profile.user:
                    name = getattr(dm_profile.user, 'name', '') or getattr(dm_profile.user, 'username', '')
                    dm_stats[dm_profile.id]['dm_name'] = name
        except LookupError:
            pass

        ranking = []
        for dm_id, stats in dm_stats.items():
            avg_rating = round(sum(stats['ratings']) / len(stats['ratings']), 2) if stats['ratings'] else 0.0
            ranking.append({
                'dm_id': stats['dm_id'],
                'dm_name': stats['dm_name'] or f'DM#{dm_id}',
                'sessions': stats['sessions'],
                'avg_rating': avg_rating,
            })

        ranking.sort(key=lambda x: (-x['sessions'], -x['avg_rating']))
        return ranking[:10]

    def _get_time_slot_analysis(self, store_id, months_back):
        try:
            from django.apps import apps
            Schedule = apps.get_model('scheduling', 'Schedule')
            Booking = apps.get_model('bookings', 'Booking')
        except LookupError:
            return []

        schedules = self._get_store_filtered_schedules(store_id, months_back)

        booking_times = {}
        try:
            booking_ids = schedules.values_list('booking_id', flat=True)
            for booking in Booking.objects.filter(id__in=booking_ids):
                booking_times[booking.id] = booking.scheduled_start
        except LookupError:
            pass

        slot_counts = {}

        for sched in schedules:
            scheduled_start = booking_times.get(sched.booking_id)
            if not scheduled_start:
                continue

            day_of_week = scheduled_start.weekday()
            hour = scheduled_start.hour
            time_slot = _get_time_slot(hour)
            if not time_slot:
                continue

            key = (day_of_week, time_slot)
            if key not in slot_counts:
                slot_counts[key] = 0
            slot_counts[key] += 1

        result = []
        for (day_of_week, time_slot), count in slot_counts.items():
            result.append({
                'day_of_week': day_of_week,
                'time_slot': time_slot,
                'count': count,
            })

        result.sort(key=lambda x: (x['day_of_week'], x['time_slot']))
        return result

    def _get_script_turnover(self, store_id):
        stats_qs = ScriptStats.objects.all()

        if store_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script_ids = Script.objects.filter(
                    store_id=store_id
                ).values_list('id', flat=True)
                stats_qs = stats_qs.filter(script_id__in=script_ids)
            except LookupError:
                pass

        stats_qs = stats_qs.order_by('-turnover_rate')[:10]

        result = []
        script_names = {}
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            for script in Script.objects.filter(
                id__in=stats_qs.values_list('script_id', flat=True)
            ):
                script_names[script.id] = script.name
        except LookupError:
            pass

        for stats in stats_qs:
            ratings = [r for r in [stats.avg_dm_rating, stats.avg_script_rating] if r > 0]
            avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
            result.append({
                'script_id': stats.script_id,
                'script_name': script_names.get(stats.script_id, f'剧本#{stats.script_id}'),
                'turnover_rate': stats.turnover_rate,
                'avg_rating': avg_rating,
            })

        return result
