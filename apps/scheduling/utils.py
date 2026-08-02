from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from django.db import models as django_models

from .models import Schedule, ScheduleConflict, ScheduleStatus, ConflictType, MIN_TURNAROUND_MINUTES

logger = logging.getLogger(__name__)


def _get_schedule_time_range(schedule: Schedule) -> Tuple[Optional[datetime], Optional[datetime]]:
    start = schedule.scheduled_start_time
    end = schedule.scheduled_end_time
    return start, end


def _times_overlap(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> bool:
    # 使用半开区间 [start, end)，首尾相接（前一场结束时间等于后一场开始时间）不算冲突
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


def _times_too_close(
    s1: datetime, e1: datetime, s2: datetime, e2: datetime,
    buffer_minutes: int = MIN_TURNAROUND_MINUTES,
) -> bool:
    # 首尾相接（间隔为 0）时同样算太近。真正重叠的属于冲突、不是提醒，由 turnaround_gap_if_too_close 返回 None 排除。
    return turnaround_gap_if_too_close(s1, e1, s2, e2, buffer_minutes) is not None


def gap_minutes_between(
    s1: datetime, e1: datetime, s2: datetime, e2: datetime,
) -> Optional[float]:
    # 两段时间的间隔分钟数；复用 _times_overlap 判定：重叠返回 None（重叠是冲突，语义上不是"间隔"）。
    if _times_overlap(s1, e1, s2, e2):
        return None
    if e1 <= s2:
        return (s2 - e1).total_seconds() / 60
    return (s1 - e2).total_seconds() / 60


def turnaround_gap_if_too_close(
    s1: datetime, e1: datetime, s2: datetime, e2: datetime,
    buffer_minutes: int = MIN_TURNAROUND_MINUTES,
) -> Optional[float]:
    # 共用入口：间隔不足 buffer_minutes（含首尾相接的 0）时返回间隔分钟数，否则返回 None。
    # 正好等于 buffer_minutes 视为足够，返回 None。重叠同样返回 None（那是冲突不是"太近"）。
    gap = gap_minutes_between(s1, e1, s2, e2)
    if gap is None or gap >= buffer_minutes:
        return None
    return gap


def detect_proximity_warnings_for_schedule(schedule: Schedule) -> List[dict]:
    start1, end1 = _get_schedule_time_range(schedule)
    if not start1 or not end1 or not schedule.dm_id or not schedule.room_id:
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

        if not _times_too_close(start1, end1, start2, end2):
            continue

        same_dm = (
            schedule.dm_id and other.dm_id and
            schedule.dm_id == other.dm_id
        )
        same_room = (
            schedule.room_id and other.room_id and
            schedule.room_id == other.room_id
        )

        if same_dm:
            warnings.append({
                'type': ConflictType.DM_CONFLICT,
                'other_schedule_id': other.id,
                'message': f'DM#{schedule.dm_id} 两场排班间隔不足 {MIN_TURNAROUND_MINUTES} 分钟，可能来不及交接',
            })

        if same_room:
            warnings.append({
                'type': ConflictType.ROOM_CONFLICT,
                'other_schedule_id': other.id,
                'message': f'房间#{schedule.room_id} 两场排班间隔不足 {MIN_TURNAROUND_MINUTES} 分钟，可能来不及收拾',
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
