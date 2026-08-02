from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from django.db import models as django_models

from .models import (
    Schedule, ScheduleConflict, ScheduleStatus, ConflictType,
    MIN_SESSION_GAP_MINUTES,
)

logger = logging.getLogger(__name__)


def _get_schedule_time_range(schedule: Schedule) -> Tuple[Optional[datetime], Optional[datetime]]:
    start = schedule.scheduled_start_time
    end = schedule.scheduled_end_time
    return start, end


def _times_overlap(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> bool:
    # 半开区间 [start, end)：首尾相接（e1 == s2 或 e2 == s1）不算重叠
    return s1 < e2 and s2 < e1


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


def detect_nearby_sessions(schedule: Schedule) -> List[dict]:
    """检测与当前排班同 DM/同房间、间隔不足 MIN_SESSION_GAP_MINUTES 的场次。

    仅用于提醒，不算冲突也不阻止排班；重叠的场次属于冲突，由
    detect_conflicts_for_schedule 处理，这里只关心首尾之间的间隔。
    """
    start1, end1 = _get_schedule_time_range(schedule)
    if not start1 or not end1:
        return []
    if not schedule.dm_id and not schedule.room_id:
        return []
    if schedule.status == ScheduleStatus.CANCELLED:
        return []

    from apps.bookings.models import BookingStatus
    inactive_booking_statuses = [BookingStatus.CANCELLED, BookingStatus.NO_SHOW]

    min_gap = timedelta(minutes=MIN_SESSION_GAP_MINUTES)
    warnings = []

    # DM 和房间两个维度各自独立匹配，未分配的维度不参与过滤
    dimension_q = django_models.Q()
    if schedule.dm_id:
        dimension_q |= django_models.Q(dm_id=schedule.dm_id)
    if schedule.room_id:
        dimension_q |= django_models.Q(room_id=schedule.room_id)

    other_schedules = Schedule.objects.filter(
        ~django_models.Q(id=schedule.id),
        ~django_models.Q(status=ScheduleStatus.CANCELLED),
        dimension_q,
    ).select_related('dm', 'room', 'booking')

    for other in other_schedules:
        booking = other.booking
        if booking and booking.status in inactive_booking_statuses:
            continue

        start2, end2 = _get_schedule_time_range(other)
        if not start2 or not end2:
            continue

        if _times_overlap(start1, end1, start2, end2):
            continue

        if end1 <= start2:
            gap = start2 - end1
        else:
            gap = start1 - end2

        if gap >= min_gap:
            continue

        gap_minutes = int(gap.total_seconds() // 60)

        is_same_dm = (
            schedule.dm_id and other.dm_id and
            schedule.dm_id == other.dm_id
        )
        is_same_room = (
            schedule.room_id and other.room_id and
            schedule.room_id == other.room_id
        )

        if is_same_dm:
            warnings.append({
                'type': 'dm',
                'schedule_id': other.id,
                'gap_minutes': gap_minutes,
                'message': f'与排班#{other.id} 间隔仅 {gap_minutes} 分钟，DM#{schedule.dm_id} 可能赶不及',
            })

        if is_same_room:
            warnings.append({
                'type': 'room',
                'schedule_id': other.id,
                'gap_minutes': gap_minutes,
                'message': f'与排班#{other.id} 间隔仅 {gap_minutes} 分钟，房间#{schedule.room_id} 可能来不及收拾',
            })

    return warnings


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
