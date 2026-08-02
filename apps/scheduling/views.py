from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Any, Optional

from django.db import models as django_models, transaction
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import UserRole

from .models import (
    Schedule,
    ScheduleConflict,
    ScheduleStatus,
    ConflictType,
)
from .serializers import (
    ScheduleSerializer,
    ScheduleCreateSerializer,
    ScheduleListSerializer,
    ScheduleDetailSerializer,
    ScheduleStatusUpdateSerializer,
    SchedulingRequestSerializer,
    SchedulingResultSerializer,
    ConflictSerializer,
    ReassignmentRequestSerializer,
    ScheduleCalendarItemSerializer,
)
from .permissions import (
    SchedulePermission,
    SchedulingPermission,
    ReassignmentPermission,
    ConflictPermission,
    _get_user_role,
    _get_user_store_id,
    _get_dm_user_id,
)
from .filters import ScheduleFilter, ScheduleConflictFilter
from .algorithms import (
    SchedulingInput,
    BookingInput,
    DMInput,
    RoomInput,
    LockedSchedule,
    DMAvailability,
    DMSkill,
    run_scheduling,
    SchedulingResult,
    ScheduleAssignment,
)
from .utils import (
    detect_conflicts_for_schedule,
    resolve_conflicts_for_schedule,
    get_consecutive_work_days,
)

logger = logging.getLogger(__name__)


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER


class ScheduleViewSet(viewsets.ModelViewSet):
    queryset = Schedule.objects.select_related('dm', 'room', 'script').all()
    permission_classes = [SchedulePermission]
    filterset_class = ScheduleFilter
    search_fields = ['booking_id']
    ordering_fields = ['created_at', 'updated_at']

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
            room_ids = Room.objects.filter(
                store_id=user_store_id
            ).values_list('id', flat=True)
            store_schedules = qs.filter(room_id__in=room_ids)
        except LookupError:
            store_schedules = qs.none()

        if role == UserRole.DM:
            dm_profile_id = _get_dm_user_id(self.request.user)
            if dm_profile_id:
                dm_schedules = qs.filter(dm_id=dm_profile_id)
                qs = store_schedules | dm_schedules
                qs = qs.distinct()
                return qs

        return store_schedules

    def get_serializer_class(self):
        if self.action == 'list':
            return ScheduleListSerializer
        if self.action == 'retrieve':
            return ScheduleDetailSerializer
        if self.action == 'create':
            return ScheduleCreateSerializer
        if self.action in ['update', 'partial_update']:
            return ScheduleSerializer
        if self.action == 'confirm_status':
            return ScheduleStatusUpdateSerializer
        return ScheduleSerializer

    def perform_update(self, serializer):
        instance = serializer.save()
        resolve_conflicts_for_schedule(instance)
        detect_conflicts_for_schedule(instance)

    def perform_destroy(self, instance):
        resolve_conflicts_for_schedule(instance)
        instance.delete()

    @action(detail=True, methods=['post'], url_path='lock')
    def lock(self, request, pk=None):
        schedule = self.get_object()
        schedule.is_locked = True
        schedule.save()
        serializer = ScheduleDetailSerializer(schedule)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='unlock')
    def unlock(self, request, pk=None):
        schedule = self.get_object()
        schedule.is_locked = False
        schedule.save()
        serializer = ScheduleDetailSerializer(schedule)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='adjust')
    def adjust(self, request, pk=None):
        schedule = self.get_object()
        if schedule.is_locked:
            return Response(
                {'detail': '已锁定的排班不能调整'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ScheduleSerializer(schedule, data=request.data, partial=True)
        if serializer.is_valid():
            with transaction.atomic():
                self.perform_update(serializer)
            return Response(ScheduleDetailSerializer(schedule).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='confirm-status')
    def confirm_status(self, request, pk=None):
        schedule = self.get_object()
        role = _get_user_role(request.user)

        if role == UserRole.DM:
            dm_profile_id = _get_dm_user_id(request.user)
            if schedule.dm_id != dm_profile_id:
                return Response(
                    {'detail': '只能确认自己的排班'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if schedule.status != ScheduleStatus.ASSIGNED:
                return Response(
                    {'detail': '当前状态不能确认'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            schedule.status = ScheduleStatus.DM_CONFIRMED
            schedule.save()
            return Response(ScheduleDetailSerializer(schedule).data)

        serializer = ScheduleStatusUpdateSerializer(
            schedule, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(ScheduleDetailSerializer(schedule).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SchedulingView(APIView):
    permission_classes = [SchedulingPermission]

    def post(self, request):
        serializer = SchedulingRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data
        start_date = validated['start_date']
        end_date = validated['end_date']
        store_id = validated['store_id']
        force_regenerate = validated.get('force_regenerate', False)

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)
        if role != PLATFORM_ADMIN and user_store_id != store_id:
            return Response(
                {'detail': '无权操作该门店'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            scheduling_input = self._build_scheduling_input(
                start_date, end_date, store_id, force_regenerate
            )
        except Exception as e:
            logger.error(f'构建排班输入失败: {e}', exc_info=True)
            return Response(
                {'detail': f'构建排班数据失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        result = run_scheduling(scheduling_input)

        with transaction.atomic():
            created_count, updated_count = self._apply_scheduling_result(
                result, store_id, force_regenerate
            )

        response_data = {
            'assignments': [
                {
                    'booking_id': a.booking_id,
                    'dm_id': a.dm_id,
                    'room_id': a.room_id,
                    'script_id': a.script_id,
                    'match_score': a.match_score,
                    'is_new': a.is_new,
                }
                for a in result.assignments
            ],
            'unassigned_bookings': result.unassigned_bookings,
            'conflicts': [
                {
                    'conflict_type': c.conflict_type,
                    'description': c.description,
                    'booking_id': c.booking_id,
                    'dm_id': c.dm_id,
                    'room_id': c.room_id,
                    'severity': c.severity,
                }
                for c in result.conflicts
            ],
            'total_score': result.total_score,
            'solver_status': result.solver_status,
            'solve_time_seconds': result.solve_time_seconds,
            'stats': {
                'created_count': created_count,
                'updated_count': updated_count,
                'total_assignments': len(result.assignments),
                'unassigned_count': len(result.unassigned_bookings),
                'conflict_count': len(result.conflicts),
            },
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _build_scheduling_input(
        self,
        start_date: date,
        end_date: date,
        store_id: int,
        force_regenerate: bool,
    ) -> SchedulingInput:
        from django.apps import apps

        bookings_input = self._load_bookings(start_date, end_date, store_id)

        dm_profiles_input = self._load_dm_profiles(store_id, start_date, end_date)

        rooms_input = self._load_rooms(store_id)

        locked_schedules = self._load_locked_schedules(
            start_date, end_date, store_id, force_regenerate
        )

        return SchedulingInput(
            bookings=bookings_input,
            dm_profiles=dm_profiles_input,
            rooms=rooms_input,
            locked_schedules=locked_schedules,
            time_window_days=(end_date - start_date).days + 1,
        )

    def _load_bookings(
        self, start_date: date, end_date: date, store_id: int
    ) -> List[BookingInput]:
        from django.apps import apps

        try:
            Booking = apps.get_model('bookings', 'Booking')
        except LookupError:
            return []

        existing_booking_ids = Schedule.objects.exclude(
            status=ScheduleStatus.CANCELLED
        ).values_list('booking_id', flat=True)

        bookings_qs = Booking.objects.filter(
            scheduled_start__date__gte=start_date,
            scheduled_start__date__lte=end_date,
            store_id=store_id,
        ).exclude(
            id__in=existing_booking_ids,
        ).select_related('script')

        result = []
        for booking in bookings_qs:
            script = getattr(booking, 'script', None)
            script_id = script.id if script else None
            script_type = getattr(script, 'type', None)

            result.append(BookingInput(
                booking_id=booking.id,
                date=booking.scheduled_start.date(),
                start_time=booking.scheduled_start,
                duration_minutes=getattr(booking, 'duration_minutes', 180),
                player_count=getattr(booking, 'player_count', 0),
                script_id=script_id,
                script_type=script_type,
                preferred_dm_ids=None,
            ))

        return result

    def _load_dm_profiles(
        self, store_id: int, start_date: date, end_date: date
    ) -> List[DMInput]:
        from django.apps import apps

        try:
            DMProfile = apps.get_model('accounts', 'DMProfile')
            User = apps.get_model('accounts', 'User')
        except LookupError:
            return []

        dm_users = User.objects.filter(
            role=UserRole.DM,
            store_id=store_id,
            is_active=True,
        ).values_list('id', flat=True)

        dm_profiles_qs = DMProfile.objects.filter(
            user_id__in=list(dm_users),
        ).select_related('user')

        result = []
        for dm_profile in dm_profiles_qs:
            user = dm_profile.user

            availabilities = self._load_dm_availabilities(
                dm_profile.id, start_date, end_date
            )

            skills = self._load_dm_skills(dm_profile.id)

            recent_types = self._get_recent_script_types(dm_profile.id)

            consecutive_days = get_consecutive_work_days(dm_profile.id)

            rest_preferences = getattr(dm_profile, 'rest_preferences', {}) or {}

            result.append(DMInput(
                dm_id=dm_profile.id,
                user_id=user.id,
                name=getattr(user, 'name', '') or getattr(user, 'username', ''),
                availabilities=availabilities,
                skills=skills,
                rest_preferences=rest_preferences,
                consecutive_work_days=consecutive_days,
                recent_script_types=recent_types,
            ))

        return result

    def _load_dm_availabilities(
        self, dm_profile_id: int, start_date: date, end_date: date
    ) -> List[DMAvailability]:
        result = []
        current = start_date
        while current <= end_date:
            result.append(DMAvailability(
                date=current,
                start_minutes=10 * 60,
                end_minutes=23 * 60,
            ))
            current += timedelta(days=1)
        return result

    def _load_dm_skills(self, dm_profile_id: int) -> List[DMSkill]:
        from django.apps import apps

        try:
            DMSkillModel = apps.get_model('accounts', 'DMSkill')
            skills_qs = DMSkillModel.objects.filter(dm_profile_id=dm_profile_id)
            return [
                DMSkill(
                    script_id=skill.script_id,
                    proficiency=getattr(skill, 'proficiency', 1),
                )
                for skill in skills_qs
            ]
        except LookupError:
            pass

        try:
            Script = apps.get_model('scripts', 'Script')
            script_ids = Script.objects.all().values_list('id', flat=True)
            return [
                DMSkill(script_id=sid, proficiency=2)
                for sid in script_ids[:5]
            ]
        except LookupError:
            return []

    def _get_recent_script_types(self, dm_profile_id: int) -> List[str]:
        from django.apps import apps
        from collections import Counter

        try:
            Script = apps.get_model('scripts', 'Script')
        except LookupError:
            return []

        recent_schedules = Schedule.objects.filter(
            dm_id=dm_profile_id,
            status__in=[
                ScheduleStatus.COMPLETED,
                ScheduleStatus.IN_PROGRESS,
                ScheduleStatus.DM_CONFIRMED,
            ],
            script_id__isnull=False,
        ).order_by('-created_at')[:10].values_list('script_id', flat=True)

        type_counts = Counter()
        for script_id in recent_schedules:
            try:
                script = Script.objects.get(pk=script_id)
                type_counts[script.type] += 1
            except Script.DoesNotExist:
                continue

        return [t for t, _ in type_counts.most_common(3)]

    def _load_rooms(self, store_id: int) -> List[RoomInput]:
        from django.apps import apps

        try:
            Room = apps.get_model('stores', 'Room')
        except LookupError:
            return []

        rooms_qs = Room.objects.filter(
            store_id=store_id,
            is_active=True,
        )

        return [
            RoomInput(
                room_id=room.id,
                name=room.name,
                store_id=room.store_id,
                capacity=room.capacity,
                is_active=room.is_active,
            )
            for room in rooms_qs
        ]

    def _load_locked_schedules(
        self,
        start_date: date,
        end_date: date,
        store_id: int,
        force_regenerate: bool,
    ) -> List[LockedSchedule]:
        from django.apps import apps
        from django.db.models.functions import TruncDate

        try:
            Booking = apps.get_model('bookings', 'Booking')
            Room = apps.get_model('stores', 'Room')
        except LookupError:
            return []

        room_ids = Room.objects.filter(store_id=store_id).values_list('id', flat=True)

        locked_statuses = [ScheduleStatus.DM_CONFIRMED, ScheduleStatus.IN_PROGRESS, ScheduleStatus.COMPLETED]

        qs = Schedule.objects.filter(
            room_id__in=room_ids,
        ).exclude(
            status=ScheduleStatus.CANCELLED,
        )

        if not force_regenerate:
            qs = qs.filter(
                django_models.Q(is_locked=True) | django_models.Q(status__in=locked_statuses)
            )
        else:
            qs = qs.filter(is_locked=True)

        existing_booking_ids = qs.values_list('booking_id', flat=True)

        booking_dates = {}
        try:
            bookings_data = Booking.objects.filter(
                id__in=existing_booking_ids,
            ).values('id', 'scheduled_start')
            for bd in bookings_data:
                booking_dates[bd['id']] = bd['scheduled_start']
        except Exception:
            pass

        result = []
        for sched in qs:
            start_dt = booking_dates.get(sched.booking_id)
            if not start_dt:
                continue

            end_dt = start_dt
            if sched.script_id:
                try:
                    Script = apps.get_model('scripts', 'Script')
                    script = Script.objects.get(pk=sched.script_id)
                    end_dt = start_dt + timedelta(minutes=script.duration_minutes)
                except Exception:
                    end_dt = start_dt + timedelta(minutes=180)

            result.append(LockedSchedule(
                schedule_id=sched.id,
                booking_id=sched.booking_id,
                dm_id=sched.dm_id or 0,
                room_id=sched.room_id or 0,
                script_id=sched.script_id or 0,
                start_time=start_dt,
                end_time=end_dt,
            ))

        return result

    def _apply_scheduling_result(
        self,
        result: SchedulingResult,
        store_id: int,
        force_regenerate: bool,
    ) -> Tuple[int, int]:
        created_count = 0
        updated_count = 0

        for assignment in result.assignments:
            defaults = {
                'dm_id': assignment.dm_id if assignment.dm_id else None,
                'room_id': assignment.room_id if assignment.room_id else None,
                'script_id': assignment.script_id if assignment.script_id else None,
                'status': ScheduleStatus.ASSIGNED,
            }

            schedule, created = Schedule.objects.update_or_create(
                booking_id=assignment.booking_id,
                defaults=defaults,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            detect_conflicts_for_schedule(schedule)

        return created_count, updated_count


class ReassignmentView(APIView):
    permission_classes = [ReassignmentPermission]

    def post(self, request):
        serializer = ReassignmentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated = serializer.validated_data
        dm_id = validated['dm_id']
        start_date = validated['start_date']
        end_date = validated['end_date']
        store_id = validated['store_id']

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)
        if role != PLATFORM_ADMIN and user_store_id != store_id:
            return Response(
                {'detail': '无权操作该门店'},
                status=status.HTTP_403_FORBIDDEN,
            )

        affected_schedules = self._find_affected_schedules(
            dm_id, start_date, end_date, store_id
        )

        if not affected_schedules:
            return Response({
                'message': '没有找到受影响的排班',
                'affected_count': 0,
                'reassigned_count': 0,
            })

        affected_booking_ids = list(
            Schedule.objects.filter(
                id__in=[s.id for s in affected_schedules]
            ).values_list('booking_id', flat=True)
        )

        with transaction.atomic():
            Schedule.objects.filter(
                id__in=[s.id for s in affected_schedules]
            ).update(dm_id=None)

            try:
                scheduling_input = self._build_reassignment_input(
                    affected_booking_ids,
                    dm_id,
                    start_date,
                    end_date,
                    store_id,
                )
                result = run_scheduling(scheduling_input)
                reassigned_count = self._apply_reassignments(result)
            except Exception as e:
                logger.error(f'重排失败: {e}', exc_info=True)
                transaction.set_rollback(True)
                return Response(
                    {'detail': f'重排失败: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response({
            'message': f'已处理 {len(affected_schedules)} 个受影响的排班',
            'affected_count': len(affected_schedules),
            'reassigned_count': reassigned_count,
            'unassigned_count': len(result.unassigned_bookings),
            'conflicts': [
                {
                    'conflict_type': c.conflict_type,
                    'description': c.description,
                    'booking_id': c.booking_id,
                }
                for c in result.conflicts
            ],
            'solver_status': result.solver_status,
            'solve_time_seconds': result.solve_time_seconds,
        })

    def _find_affected_schedules(
        self,
        dm_id: int,
        start_date: date,
        end_date: date,
        store_id: int,
    ) -> List[Schedule]:
        from django.apps import apps

        affected = []
        schedules = Schedule.objects.filter(
            dm_id=dm_id,
        ).exclude(
            status__in=[
                ScheduleStatus.COMPLETED,
                ScheduleStatus.CANCELLED,
            ]
        ).select_related('booking')

        for sched in schedules:
            if sched.is_locked:
                continue
            if sched.status == ScheduleStatus.DM_CONFIRMED:
                continue

            try:
                Booking = apps.get_model('bookings', 'Booking')
                booking = Booking.objects.get(pk=sched.booking_id)
                sched_date = booking.scheduled_start.date()
                if start_date <= sched_date <= end_date:
                    affected.append(sched)
            except Exception:
                continue

        return affected

    def _build_reassignment_input(
        self,
        booking_ids: List[int],
        exclude_dm_id: int,
        start_date: date,
        end_date: date,
        store_id: int,
    ) -> SchedulingInput:
        from django.apps import apps

        bookings_input = []
        try:
            Booking = apps.get_model('bookings', 'Booking')
            for booking in Booking.objects.filter(id__in=booking_ids).select_related('script'):
                script = getattr(booking, 'script', None)
                bookings_input.append(BookingInput(
                    booking_id=booking.id,
                    date=booking.scheduled_start.date(),
                    start_time=booking.scheduled_start,
                    duration_minutes=getattr(booking, 'duration_minutes', 180),
                    player_count=getattr(booking, 'player_count', 0),
                    script_id=script.id if script else None,
                    script_type=getattr(script, 'type', None),
                ))
        except LookupError:
            pass

        dm_profiles = self._load_dm_profiles_excluding(store_id, exclude_dm_id, start_date, end_date)

        rooms_input = []
        try:
            Room = apps.get_model('stores', 'Room')
            for room in Room.objects.filter(store_id=store_id, is_active=True):
                rooms_input.append(RoomInput(
                    room_id=room.id,
                    name=room.name,
                    store_id=room.store_id,
                    capacity=room.capacity,
                    is_active=room.is_active,
                ))
        except LookupError:
            pass

        locked_schedules = self._load_locked_for_reassignment(
            start_date, end_date, store_id, booking_ids
        )

        return SchedulingInput(
            bookings=bookings_input,
            dm_profiles=dm_profiles,
            rooms=rooms_input,
            locked_schedules=locked_schedules,
        )

    def _load_dm_profiles_excluding(
        self,
        store_id: int,
        exclude_dm_id: int,
        start_date: date,
        end_date: date,
    ) -> List[DMInput]:
        from django.apps import apps

        result = []
        try:
            DMProfile = apps.get_model('accounts', 'DMProfile')
            User = apps.get_model('accounts', 'User')

            dm_users = User.objects.filter(
                role=UserRole.DM,
                store_id=store_id,
                is_active=True,
            ).values_list('id', flat=True)

            for dm_profile in DMProfile.objects.filter(
                user_id__in=list(dm_users),
            ).exclude(id=exclude_dm_id).select_related('user'):
                user = dm_profile.user
                availabilities = []
                current = start_date
                while current <= end_date:
                    availabilities.append(DMAvailability(
                        date=current,
                        start_minutes=10 * 60,
                        end_minutes=23 * 60,
                    ))
                    current += timedelta(days=1)

                skills = []
                try:
                    Script = apps.get_model('scripts', 'Script')
                    for sid in Script.objects.all().values_list('id', flat=True)[:5]:
                        skills.append(DMSkill(script_id=sid, proficiency=2))
                except LookupError:
                    pass

                result.append(DMInput(
                    dm_id=dm_profile.id,
                    user_id=user.id,
                    name=getattr(user, 'name', '') or getattr(user, 'username', ''),
                    availabilities=availabilities,
                    skills=skills,
                    rest_preferences={},
                    consecutive_work_days=get_consecutive_work_days(dm_profile.id),
                    recent_script_types=[],
                ))
        except LookupError:
            pass

        return result

    def _load_locked_for_reassignment(
        self,
        start_date: date,
        end_date: date,
        store_id: int,
        exclude_booking_ids: List[int],
    ) -> List[LockedSchedule]:
        from django.apps import apps

        result = []
        try:
            Booking = apps.get_model('bookings', 'Booking')
            Room = apps.get_model('stores', 'Room')
            Script = apps.get_model('scripts', 'Script')

            room_ids = Room.objects.filter(store_id=store_id).values_list('id', flat=True)
            locked_qs = Schedule.objects.filter(
                room_id__in=room_ids,
                is_locked=True,
            ).exclude(
                booking_id__in=exclude_booking_ids,
            )

            booking_starts = dict(
                Booking.objects.filter(
                    id__in=locked_qs.values_list('booking_id', flat=True)
                ).values_list('id', 'scheduled_start')
            )

            for sched in locked_qs:
                start_dt = booking_starts.get(sched.booking_id)
                if not start_dt:
                    continue
                duration = 180
                if sched.script_id:
                    try:
                        script = Script.objects.get(pk=sched.script_id)
                        duration = script.duration_minutes
                    except Exception:
                        pass
                result.append(LockedSchedule(
                    schedule_id=sched.id,
                    booking_id=sched.booking_id,
                    dm_id=sched.dm_id or 0,
                    room_id=sched.room_id or 0,
                    script_id=sched.script_id or 0,
                    start_time=start_dt,
                    end_time=start_dt + timedelta(minutes=duration),
                ))
        except LookupError:
            pass

        return result

    def _apply_reassignments(self, result: SchedulingResult) -> int:
        reassigned = 0
        for assignment in result.assignments:
            updated = Schedule.objects.filter(
                booking_id=assignment.booking_id,
                is_locked=False,
            ).exclude(
                status__in=[
                    ScheduleStatus.DM_CONFIRMED,
                    ScheduleStatus.IN_PROGRESS,
                    ScheduleStatus.COMPLETED,
                ]
            ).update(
                dm_id=assignment.dm_id if assignment.dm_id else None,
                room_id=assignment.room_id if assignment.room_id else None,
                script_id=assignment.script_id if assignment.script_id else None,
                status=ScheduleStatus.ASSIGNED,
            )
            if updated:
                reassigned += 1

                try:
                    sched = Schedule.objects.get(booking_id=assignment.booking_id)
                    resolve_conflicts_for_schedule(sched)
                    detect_conflicts_for_schedule(sched)
                except Schedule.DoesNotExist:
                    pass

        return reassigned


class ConflictViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    queryset = ScheduleConflict.objects.select_related(
        'schedule1', 'schedule2',
        'schedule1__dm', 'schedule2__dm',
        'schedule1__room', 'schedule2__room',
    ).all()
    permission_classes = [ConflictPermission]
    filterset_class = ScheduleConflictFilter
    serializer_class = ConflictSerializer
    ordering_fields = ['created_at']

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
            room_ids = list(Room.objects.filter(store_id=user_store_id).values_list('id', flat=True))

            store_schedule_ids = list(Schedule.objects.filter(
                room_id__in=room_ids
            ).values_list('id', flat=True))

            qs = qs.filter(
                django_models.Q(schedule1_id__in=store_schedule_ids) |
                django_models.Q(schedule2_id__in=store_schedule_ids)
            )
        except LookupError:
            pass

        if role == UserRole.DM:
            dm_profile_id = _get_dm_user_id(self.request.user)
            if dm_profile_id:
                dm_schedule_ids = list(Schedule.objects.filter(
                    dm_id=dm_profile_id
                ).values_list('id', flat=True))
                dm_qs = qs.filter(
                    django_models.Q(schedule1_id__in=dm_schedule_ids) |
                    django_models.Q(schedule2_id__in=dm_schedule_ids)
                )
                qs = qs | dm_qs
                qs = qs.distinct()

        return qs

    @action(detail=True, methods=['post'], url_path='mark-resolved')
    def mark_resolved(self, request, pk=None):
        conflict = self.get_object()
        conflict.resolved = True
        conflict.save()
        return Response(ConflictSerializer(conflict).data)

    @action(detail=False, methods=['post'], url_path='bulk-resolve')
    def bulk_resolve(self, request):
        conflict_ids = request.data.get('ids', [])
        if not conflict_ids:
            return Response(
                {'detail': '请提供要解决的冲突ID列表'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)

        qs = ScheduleConflict.objects.filter(id__in=conflict_ids)
        if role != PLATFORM_ADMIN:
            try:
                from django.apps import apps
                Room = apps.get_model('stores', 'Room')
                room_ids = list(Room.objects.filter(store_id=user_store_id).values_list('id', flat=True))
                store_sched_ids = list(Schedule.objects.filter(room_id__in=room_ids).values_list('id', flat=True))
                qs = qs.filter(
                    schedule1_id__in=store_sched_ids,
                    schedule2_id__in=store_sched_ids,
                )
            except LookupError:
                pass

        count = qs.update(resolved=True)
        return Response({'resolved_count': count})


class ScheduleCalendarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start_str = request.query_params.get('start')
        end_str = request.query_params.get('end')
        store_id = request.query_params.get('store_id')
        dm_id = request.query_params.get('dm_id')
        room_id = request.query_params.get('room_id')

        if not start_str or not end_str:
            return Response(
                {'detail': '请提供start和end日期参数'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
        except ValueError:
            return Response(
                {'detail': '日期格式错误，请使用ISO格式'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)

        if role != PLATFORM_ADMIN:
            if store_id and int(store_id) != user_store_id:
                return Response(
                    {'detail': '无权查看该门店数据'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            store_id = user_store_id

        schedules = self._load_calendar_schedules(
            start_date, end_date, store_id, dm_id, room_id
        )

        calendar_items = self._build_calendar_items(schedules, request.user)

        return Response(calendar_items)

    def _load_calendar_schedules(
        self,
        start_date: date,
        end_date: date,
        store_id: Optional[int],
        dm_id: Optional[str],
        room_id: Optional[str],
    ):
        from django.apps import apps

        qs = Schedule.objects.exclude(
            status=ScheduleStatus.CANCELLED,
        ).select_related('dm', 'room', 'script')

        if store_id:
            try:
                Room = apps.get_model('stores', 'Room')
                room_ids = Room.objects.filter(store_id=store_id).values_list('id', flat=True)
                qs = qs.filter(room_id__in=room_ids)
            except LookupError:
                pass

        if dm_id:
            qs = qs.filter(dm_id=int(dm_id))

        if room_id:
            qs = qs.filter(room_id=int(room_id))

        try:
            Booking = apps.get_model('bookings', 'Booking')
            booking_ids = Booking.objects.filter(
                scheduled_start__date__gte=start_date,
                scheduled_start__date__lte=end_date,
            ).values_list('id', flat=True)
            qs = qs.filter(booking_id__in=booking_ids)
        except LookupError:
            pass

        return qs

    def _build_calendar_items(self, schedules, user) -> List[Dict[str, Any]]:
        from django.apps import apps

        status_colors = {
            ScheduleStatus.ASSIGNED: '#3B82F6',
            ScheduleStatus.DM_CONFIRMED: '#10B981',
            ScheduleStatus.IN_PROGRESS: '#F59E0B',
            ScheduleStatus.COMPLETED: '#6B7280',
            ScheduleStatus.CANCELLED: '#EF4444',
        }

        booking_starts = {}
        try:
            Booking = apps.get_model('bookings', 'Booking')
            for b in Booking.objects.filter(
                id__in=schedules.values_list('booking_id', flat=True)
            ).values('id', 'scheduled_start'):
                booking_starts[b['id']] = b['scheduled_start']
        except LookupError:
            pass

        items = []
        for sched in schedules:
            start_dt = booking_starts.get(sched.booking_id)
            if not start_dt:
                continue

            duration = 180
            if sched.script_id:
                try:
                    Script = apps.get_model('scripts', 'Script')
                    script = Script.objects.filter(pk=sched.script_id).first()
                    if script:
                        duration = script.duration_minutes
                except LookupError:
                    pass

            end_dt = start_dt + timedelta(minutes=duration)

            dm_name = ''
            if sched.dm_id:
                try:
                    DMProfile = apps.get_model('accounts', 'DMProfile')
                    dm = DMProfile.objects.filter(pk=sched.dm_id).select_related('user').first()
                    if dm and dm.user:
                        dm_name = getattr(dm.user, 'name', '') or getattr(dm.user, 'username', '')
                except LookupError:
                    pass

            room_name = getattr(sched.room, 'name', '') if sched.room else ''
            script_name = getattr(sched.script, 'name', '') if sched.script else ''

            title_parts = []
            if script_name:
                title_parts.append(script_name)
            if dm_name:
                title_parts.append(f'DM:{dm_name}')
            if room_name:
                title_parts.append(f'房间:{room_name}')

            title = ' | '.join(title_parts) if title_parts else f'排班#{sched.id}'

            if sched.is_locked:
                title = '🔒 ' + title

            resource_id = f'room_{sched.room_id}' if sched.room_id else f'unknown'

            items.append({
                'id': sched.id,
                'title': title,
                'start': start_dt.isoformat(),
                'end': end_dt.isoformat(),
                'resourceId': resource_id,
                'color': status_colors.get(sched.status, '#3B82F6'),
                'extendedProps': {
                    'schedule_id': sched.id,
                    'booking_id': sched.booking_id,
                    'dm_id': sched.dm_id,
                    'dm_name': dm_name,
                    'room_id': sched.room_id,
                    'room_name': room_name,
                    'script_id': sched.script_id,
                    'script_name': script_name,
                    'status': sched.status,
                    'status_display': sched.get_status_display(),
                    'is_locked': sched.is_locked,
                    'player_count': sched.player_count,
                },
            })

        return items
