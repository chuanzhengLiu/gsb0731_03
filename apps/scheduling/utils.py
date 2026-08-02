from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from django.db import models as django_models

from .models import Schedule, ScheduleConflict, ScheduleStatus, ConflictType

logger = logging.getLogger(__name__)

MIN_SCHEDULE_GAP_MINUTES = 30


def _get_schedule_time_range(schedule: Schedule) -> Tuple[Optional[datetime], Optional[datetime]]:
    start = schedule.scheduled_start_time
    end = schedule.scheduled_end_time
    return start, end


def _times_overlap(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> bool:
    return s1 < e2 and s2 < e1


def _gap_minutes_between(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> int:
    if _times_overlap(s1, e1, s2, e2):
        return 0
    if e1 <= s2:
        gap = s2 - e1
    else:
        gap = s1 - e2
    return int(gap.total_seconds() // 60)


def get_dm_unavailabilities(
    start: datetime,
    end: datetime,
    store_id: Optional[int] = None,
    exclude_schedule_id: Optional[int] = None,
) -> Dict[int, dict]:
    from apps.bookings.models import BookingStatus

    qs = Schedule.objects.filter(
        ~django_models.Q(status=ScheduleStatus.CANCELLED),
        dm_id__isnull=False,
        booking__isnull=False,
    ).exclude(
        booking__status__in=[BookingStatus.CANCELLED, BookingStatus.NO_SHOW]
    ).select_related('booking', 'dm', 'dm__user')

    if exclude_schedule_id is not None:
        qs = qs.exclude(id=exclude_schedule_id)

    if store_id is not None:
        qs = qs.filter(dm__user__store_id=store_id)

    date_filter_start = (start - timedelta(days=1)).date()
    date_filter_end = (end + timedelta(days=1)).date()
    qs = qs.filter(booking__date__gte=date_filter_start, booking__date__lte=date_filter_end)

    result: Dict[int, dict] = {}
    for schedule in qs:
        sched_start = schedule.scheduled_start_time
        sched_end = schedule.scheduled_end_time
        if not sched_start or not sched_end:
            continue
        gap = _gap_minutes_between(start, end, sched_start, sched_end)
        if gap >= MIN_SCHEDULE_GAP_MINUTES:
            continue
        dm_id = schedule.dm_id
        if dm_id not in result or gap < result[dm_id]['gap_minutes']:
            result[dm_id] = {
                'dm_id': dm_id,
                'schedule_id': schedule.id,
                'gap_minutes': gap,
            }
    return result


def detect_conflicts_for_schedule(schedule: Schedule) -> List[ScheduleConflict]:
    start1, end1 = _get_schedule_time_range(schedule)
    if not start1 or not end1 or not schedule.dm_id or not schedule.room_id:
        return []

    conflicts_created = []

    other_schedules = Schedule.objects.filter(
        ~django_models.Q(id=schedule.id),
        ~django_models.Q(status=ScheduleStatus.CANCELLED),
    ).select_related('dm', 'room')

    for other in other_schedules:
        start2, end2 = _get_schedule_time_range(other)
        if not start2 or not end2:
            continue

        overlap = _times_overlap(start1, end1, start2, end2)
        if not overlap:
            continue

        is_dm_conflict = (
            schedule.dm_id and other.dm_id and
            schedule.dm_id == other.dm_id
        )
        is_room_conflict = (
            schedule.room_id and other.room_id and
            schedule.room_id == other.room_id
        )

        if is_dm_conflict:
            conflict = _create_or_update_conflict(
                schedule, other,
                ConflictType.DM_CONFLICT,
                f'DM#{schedule.dm_id} 时间冲突: {start1.strftime("%Y-%m-%d %H:%M")}-{end1.strftime("%H:%M")} 与 {start2.strftime("%H:%M")}-{end2.strftime("%H:%M")} 重叠'
            )
            if conflict:
                conflicts_created.append(conflict)

        if is_room_conflict:
            conflict = _create_or_update_conflict(
                schedule, other,
                ConflictType.ROOM_CONFLICT,
                f'房间#{schedule.room_id} 时间冲突: {start1.strftime("%Y-%m-%d %H:%M")}-{end1.strftime("%H:%M")} 与 {start2.strftime("%H:%M")}-{end2.strftime("%H:%M")} 重叠'
            )
            if conflict:
                conflicts_created.append(conflict)

        if overlap and not is_dm_conflict and not is_room_conflict:
            pass

    return conflicts_created


def _create_or_update_conflict(
    sched1: Schedule,
    sched2: Schedule,
    conflict_type: str,
    description: str,
) -> Optional[ScheduleConflict]:
    sched_a, sched_b = (
        (sched1, sched2) if sched1.id <= sched2.id else (sched2, sched1)
    )

    existing = ScheduleConflict.objects.filter(
        schedule1=sched_a,
        schedule2=sched_b,
        conflict_type=conflict_type,
    ).first()

    if existing:
        existing.resolved = False
        existing.description = description
        existing.save()
        return existing

    return ScheduleConflict.objects.create(
        schedule1=sched_a,
        schedule2=sched_b,
        conflict_type=conflict_type,
        description=description,
        resolved=False,
    )


def bulk_detect_conflicts(schedules: Optional[List[Schedule]] = None) -> int:
    if schedules is None:
        schedules = list(
            Schedule.objects.filter(
                ~django_models.Q(status=ScheduleStatus.CANCELLED)
            ).select_related('dm', 'room')
        )

    ScheduleConflict.objects.all().update(resolved=True)

    conflict_count = 0
    for i in range(len(schedules)):
        for j in range(i + 1, len(schedules)):
            sched_a = schedules[i]
            sched_b = schedules[j]

            start_a, end_a = _get_schedule_time_range(sched_a)
            start_b, end_b = _get_schedule_time_range(sched_b)

            if not start_a or not end_a or not start_b or not end_b:
                continue

            if not _times_overlap(start_a, end_a, start_b, end_b):
                continue

            is_dm_conflict = (
                sched_a.dm_id and sched_b.dm_id and
                sched_a.dm_id == sched_b.dm_id
            )
            is_room_conflict = (
                sched_a.room_id and sched_b.room_id and
                sched_a.room_id == sched_b.room_id
            )

            if is_dm_conflict:
                _create_or_update_conflict(
                    sched_a, sched_b,
                    ConflictType.DM_CONFLICT,
                    f'DM#{sched_a.dm_id} 时间冲突'
                )
                conflict_count += 1

            if is_room_conflict:
                _create_or_update_conflict(
                    sched_a, sched_b,
                    ConflictType.ROOM_CONFLICT,
                    f'房间#{sched_a.room_id} 时间冲突'
                )
                conflict_count += 1

    return conflict_count


def resolve_conflicts_for_schedule(schedule: Schedule) -> int:
    qs = ScheduleConflict.objects.filter(
        django_models.Q(schedule1=schedule) | django_models.Q(schedule2=schedule)
    )
    count = qs.filter(resolved=False).count()
    qs.update(resolved=True)
    return count


def get_schedule_gap_warnings(schedule: Schedule) -> List[dict]:
    start1, end1 = _get_schedule_time_range(schedule)
    if not start1 or not end1:
        return []

    warnings = []

    other_schedules = Schedule.objects.filter(
        ~django_models.Q(id=schedule.id),
        ~django_models.Q(status=ScheduleStatus.CANCELLED),
    ).select_related('dm', 'room')

    for other in other_schedules:
        start2, end2 = _get_schedule_time_range(other)
        if not start2 or not end2:
            continue

        if _times_overlap(start1, end1, start2, end2):
            continue

        gap_minutes = _gap_minutes_between(start1, end1, start2, end2)

        if gap_minutes >= MIN_SCHEDULE_GAP_MINUTES:
            continue

        if schedule.dm_id and other.dm_id and schedule.dm_id == other.dm_id:
            warnings.append({
                'type': 'dm_gap',
                'schedule_id': other.id,
                'gap_minutes': gap_minutes,
                'message': (
                    f'与排班#{other.id}间隔仅{gap_minutes}分钟，DM可能赶不及'
                ),
            })

        if schedule.room_id and other.room_id and schedule.room_id == other.room_id:
            warnings.append({
                'type': 'room_gap',
                'schedule_id': other.id,
                'gap_minutes': gap_minutes,
                'message': (
                    f'与排班#{other.id}间隔仅{gap_minutes}分钟，房间可能来不及收拾'
                ),
            })

    return warnings


def get_consecutive_work_days(dm_id: int, up_to_date: Optional[datetime] = None) -> int:
    from django.db.models.functions import TruncDate

    if up_to_date is None:
        up_to_date = datetime.now()

    try:
        from django.apps import apps
        Booking = apps.get_model('bookings', 'Booking')

        recent_schedules = Schedule.objects.filter(
            dm_id=dm_id,
            status__in=[
                ScheduleStatus.ASSIGNED,
                ScheduleStatus.DM_CONFIRMED,
                ScheduleStatus.IN_PROGRESS,
                ScheduleStatus.COMPLETED,
            ],
            booking__isnull=False,
        ).values_list('booking_id', flat=True)

        work_dates = Booking.objects.filter(
            id__in=recent_schedules,
            scheduled_start__date__lte=up_to_date.date(),
        ).annotate(
            work_date=TruncDate('scheduled_start')
        ).values_list('work_date', flat=True).distinct().order_by('-work_date')[:6]

        work_dates = sorted(work_dates, reverse=True)
        if not work_dates:
            return 0

        consecutive = 1
        prev_date = work_dates[0]

        for work_date in work_dates[1:]:
            diff = (prev_date - work_date).days
            if diff == 1:
                consecutive += 1
                prev_date = work_date
            else:
                break

        return consecutive

    except LookupError:
        return 0
