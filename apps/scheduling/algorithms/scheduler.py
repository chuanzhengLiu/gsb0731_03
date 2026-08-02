from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)


@dataclass
class BookingInput:
    booking_id: int
    date: date
    start_time: datetime
    duration_minutes: int
    player_count: int
    script_id: Optional[int] = None
    script_type: Optional[str] = None
    preferred_dm_ids: Optional[List[int]] = None

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(minutes=self.duration_minutes)

    def to_minutes_of_day(self, ref_date: date) -> Tuple[int, int]:
        start_dt = self.start_time
        end_dt = self.end_time
        day_offset = (start_dt.date() - ref_date).days
        start_min = day_offset * 24 * 60 + start_dt.hour * 60 + start_dt.minute
        end_min = day_offset * 24 * 60 + end_dt.hour * 60 + end_dt.minute
        return start_min, end_min


@dataclass
class DMAvailability:
    date: date
    start_minutes: int
    end_minutes: int


@dataclass
class DMSkill:
    script_id: int
    proficiency: int


@dataclass
class DMInput:
    dm_id: int
    user_id: int
    name: str
    availabilities: List[DMAvailability] = field(default_factory=list)
    skills: List[DMSkill] = field(default_factory=list)
    rest_preferences: Dict[str, Any] = field(default_factory=dict)
    consecutive_work_days: int = 0
    recent_script_types: List[str] = field(default_factory=list)

    def is_available(self, start_dt: datetime, end_dt: datetime) -> bool:
        target_date = start_dt.date()
        start_min = start_dt.hour * 60 + start_dt.minute
        end_min = end_dt.hour * 60 + end_dt.minute
        for avail in self.availabilities:
            if avail.date == target_date:
                if avail.start_minutes <= start_min and avail.end_minutes >= end_min:
                    return True
        return False

    def get_skill(self, script_id: int) -> Optional[DMSkill]:
        for skill in self.skills:
            if skill.script_id == script_id:
                return skill
        return None

    def get_proficiency(self, script_id: int) -> int:
        skill = self.get_skill(script_id)
        return skill.proficiency if skill else 0


@dataclass
class RoomInput:
    room_id: int
    name: str
    store_id: int
    capacity: int
    is_active: bool = True


@dataclass
class LockedSchedule:
    schedule_id: int
    booking_id: int
    dm_id: int
    room_id: int
    script_id: int
    start_time: datetime
    end_time: datetime


@dataclass
class SchedulingInput:
    bookings: List[BookingInput]
    dm_profiles: List[DMInput]
    rooms: List[RoomInput]
    locked_schedules: List[LockedSchedule] = field(default_factory=list)
    time_window_days: int = 7


@dataclass
class ScheduleAssignment:
    booking_id: int
    dm_id: int
    room_id: int
    script_id: int
    match_score: float = 0.0
    is_new: bool = True


@dataclass
class ConflictReport:
    conflict_type: str
    description: str
    booking_id: Optional[int] = None
    dm_id: Optional[int] = None
    room_id: Optional[int] = None
    severity: str = 'warning'


@dataclass
class SchedulingResult:
    assignments: List[ScheduleAssignment] = field(default_factory=list)
    unassigned_bookings: List[int] = field(default_factory=list)
    conflicts: List[ConflictReport] = field(default_factory=list)
    total_score: float = 0.0
    solver_status: str = 'unknown'
    solve_time_seconds: float = 0.0


class Scheduler:
    WEIGHT_HIGH_SKILL = 100
    WEIGHT_AVOID_SAME_TYPE = 50
    WEIGHT_REST_PREFERENCE = 40
    WEIGHT_WORKLOAD_BALANCE = 20

    MAX_SOLVE_TIME_SECONDS = 3.0
    CONSECUTIVE_DAYS_LIMIT = 5

    def __init__(self, input_data: SchedulingInput):
        self.input = input_data
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.result = SchedulingResult()

        self._booking_idx: Dict[int, int] = {}
        self._dm_idx: Dict[int, int] = {}
        self._room_idx: Dict[int, int] = {}
        self._script_ids: List[int] = []

        self._dm_assigned_counts: Dict[int, Any] = {}
        self._assignment_vars: Dict[Tuple[int, int, int, int], Any] = {}
        self._booking_dm_vars: Dict[Tuple[int, int], Any] = {}
        self._booking_room_vars: Dict[Tuple[int, int], Any] = {}
        self._booking_script_vars: Dict[Tuple[int, int], Any] = {}

    def schedule(self) -> SchedulingResult:
        logger.info(f"开始排班: {len(self.input.bookings)} 个预约, "
                    f"{len(self.input.dm_profiles)} 个DM, "
                    f"{len(self.input.rooms)} 个房间")

        self._build_indices()

        if not self.input.bookings:
            self.result.solver_status = 'optimal'
            return self.result

        self._create_variables()
        self._add_hard_constraints()
        self._add_soft_constraints_objective()

        self.solver.parameters.max_time_in_seconds = self.MAX_SOLVE_TIME_SECONDS
        self.solver.parameters.num_search_workers = 4

        start_time = datetime.now()
        status = self.solver.Solve(self.model)
        solve_time = (datetime.now() - start_time).total_seconds()
        self.result.solve_time_seconds = solve_time

        status_map = {
            cp_model.OPTIMAL: 'optimal',
            cp_model.FEASIBLE: 'feasible',
            cp_model.INFEASIBLE: 'infeasible',
            cp_model.MODEL_INVALID: 'invalid',
            cp_model.UNKNOWN: 'unknown',
        }
        self.result.solver_status = status_map.get(status, 'unknown')
        logger.info(f"求解状态: {self.result.solver_status}, 耗时: {solve_time:.2f}s")

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self._extract_solution()
            self.result.total_score = self.solver.ObjectiveValue()
        else:
            self._fallback_greedy_schedule()
            self._detect_conflicts()

        return self.result

    def _build_indices(self):
        for idx, booking in enumerate(self.input.bookings):
            self._booking_idx[booking.booking_id] = idx

        for idx, dm in enumerate(self.input.dm_profiles):
            self._dm_idx[dm.dm_id] = idx

        for idx, room in enumerate(self.input.rooms):
            self._room_idx[room.room_id] = idx

        script_set = set()
        for booking in self.input.bookings:
            if booking.script_id:
                script_set.add(booking.script_id)
        self._script_ids = sorted(script_set)

    def _create_variables(self):
        num_bookings = len(self.input.bookings)
        num_dms = len(self.input.dm_profiles)
        num_rooms = len(self.input.rooms)
        num_scripts = len(self._script_ids)

        for b in range(num_bookings):
            booking = self.input.bookings[b]
            for d in range(num_dms):
                dm = self.input.dm_profiles[d]
                key = (b, d)
                self._booking_dm_vars[key] = self.model.NewBoolVar(
                    f'b{b}_dm{d}'
                )

            for r in range(num_rooms):
                room = self.input.rooms[r]
                key = (b, r)
                self._booking_room_vars[key] = self.model.NewBoolVar(
                    f'b{b}_room{r}'
                )

            if booking.script_id:
                script_idx = self._script_ids.index(booking.script_id)
                key = (b, script_idx)
                self._booking_script_vars[key] = self.model.NewBoolVar(
                    f'b{b}_script{script_idx}'
                )
                self.model.Add(self._booking_script_vars[key] == 1)

    def _add_hard_constraints(self):
        num_bookings = len(self.input.bookings)
        num_dms = len(self.input.dm_profiles)
        num_rooms = len(self.input.rooms)

        for b in range(num_bookings):
            booking = self.input.bookings[b]

            dm_sum = sum(self._booking_dm_vars[(b, d)] for d in range(num_dms))
            self.model.AddExactlyOne(dm_sum) if num_dms > 0 else None

            room_sum = sum(self._booking_room_vars[(b, r)] for r in range(num_rooms))
            self.model.AddExactlyOne(room_sum) if num_rooms > 0 else None

            for d_idx in range(num_dms):
                dm = self.input.dm_profiles[d_idx]
                start_dt = booking.start_time
                end_dt = booking.end_time

                if not dm.is_available(start_dt, end_dt):
                    self.model.Add(self._booking_dm_vars[(b, d_idx)] == 0)

                if booking.script_id:
                    proficiency = dm.get_proficiency(booking.script_id)
                    if proficiency < 1:
                        is_locked = any(
                            ls.booking_id == booking.booking_id and ls.dm_id == dm.dm_id
                            for ls in self.input.locked_schedules
                        )
                        if not is_locked:
                            self.model.Add(self._booking_dm_vars[(b, d_idx)] == 0)

                if dm.consecutive_work_days >= self.CONSECUTIVE_DAYS_LIMIT:
                    self.model.Add(self._booking_dm_vars[(b, d_idx)] == 0)

            for r_idx in range(num_rooms):
                room = self.input.rooms[r_idx]
                if booking.player_count > room.capacity:
                    self.model.Add(self._booking_room_vars[(b, r_idx)] == 0)
                if not room.is_active:
                    self.model.Add(self._booking_room_vars[(b, r_idx)] == 0)

        for i in range(num_bookings):
            for j in range(i + 1, num_bookings):
                booking_i = self.input.bookings[i]
                booking_j = self.input.bookings[j]

                if self._times_overlap(
                    booking_i.start_time, booking_i.end_time,
                    booking_j.start_time, booking_j.end_time
                ):
                    for d_idx in range(num_dms):
                        self.model.Add(
                            self._booking_dm_vars[(i, d_idx)] +
                            self._booking_dm_vars[(j, d_idx)] <= 1
                        )

                    for r_idx in range(num_rooms):
                        self.model.Add(
                            self._booking_room_vars[(i, r_idx)] +
                            self._booking_room_vars[(j, r_idx)] <= 1
                        )

        for locked in self.input.locked_schedules:
            if locked.booking_id not in self._booking_idx:
                continue
            b_idx = self._booking_idx[locked.booking_id]

            if locked.dm_id in self._dm_idx:
                d_idx = self._dm_idx[locked.dm_id]
                self.model.Add(self._booking_dm_vars[(b_idx, d_idx)] == 1)

            if locked.room_id in self._room_idx:
                r_idx = self._room_idx[locked.room_id]
                self.model.Add(self._booking_room_vars[(b_idx, r_idx)] == 1)

    def _add_soft_constraints_objective(self):
        num_bookings = len(self.input.bookings)
        num_dms = len(self.input.dm_profiles)

        score_terms = []

        for b in range(num_bookings):
            booking = self.input.bookings[b]

            for d_idx in range(num_dms):
                dm = self.input.dm_profiles[d_idx]
                var = self._booking_dm_vars[(b, d_idx)]

                if booking.script_id:
                    proficiency = dm.get_proficiency(booking.script_id)
                    if proficiency >= 3:
                        score_terms.append(var * self.WEIGHT_HIGH_SKILL * proficiency)
                    elif proficiency >= 1:
                        score_terms.append(var * self.WEIGHT_HIGH_SKILL * proficiency // 2)

                if booking.script_type and booking.script_type in dm.recent_script_types:
                    score_terms.append(var * (-self.WEIGHT_AVOID_SAME_TYPE))

                if self._check_rest_preference_violation(dm, booking):
                    score_terms.append(var * (-self.WEIGHT_REST_PREFERENCE))

        if num_dms > 0 and num_bookings > 0:
            target_load = num_bookings / num_dms
            for d_idx in range(num_dms):
                dm = self.input.dm_profiles[d_idx]
                assigned_count = sum(
                    self._booking_dm_vars[(b, d_idx)] for b in range(num_bookings)
                )
                self._dm_assigned_counts[d_idx] = assigned_count

                diff_var = self.model.NewIntVar(0, num_bookings, f'load_diff_{d_idx}')
                self.model.AddAbsEquality(
                    diff_var,
                    assigned_count - int(target_load)
                )
                score_terms.append(diff_var * (-self.WEIGHT_WORKLOAD_BALANCE))

        if score_terms:
            self.model.Maximize(sum(score_terms))

    def _extract_solution(self):
        num_bookings = len(self.input.bookings)
        num_dms = len(self.input.dm_profiles)
        num_rooms = len(self.input.rooms)

        dm_id_list = [dm.dm_id for dm in self.input.dm_profiles]
        room_id_list = [room.room_id for room in self.input.rooms]

        for b in range(num_bookings):
            booking = self.input.bookings[b]
            assigned_dm = None
            assigned_room = None
            score = 0.0

            for d_idx in range(num_dms):
                if self.solver.Value(self._booking_dm_vars[(b, d_idx)]) == 1:
                    assigned_dm = dm_id_list[d_idx]
                    dm = self.input.dm_profiles[d_idx]
                    if booking.script_id:
                        prof = dm.get_proficiency(booking.script_id)
                        score += prof * 10

            for r_idx in range(num_rooms):
                if self.solver.Value(self._booking_room_vars[(b, r_idx)]) == 1:
                    assigned_room = room_id_list[r_idx]

            if assigned_dm and assigned_room:
                self.result.assignments.append(ScheduleAssignment(
                    booking_id=booking.booking_id,
                    dm_id=assigned_dm,
                    room_id=assigned_room,
                    script_id=booking.script_id or 0,
                    match_score=score,
                    is_new=True,
                ))
            else:
                self.result.unassigned_bookings.append(booking.booking_id)

    def _fallback_greedy_schedule(self):
        logger.warning("CP-SAT求解失败，使用贪心算法降级排班")

        sorted_bookings = sorted(
            self.input.bookings,
            key=lambda b: b.player_count,
            reverse=True
        )
        dm_workload = defaultdict(int)
        dm_booked_times: Dict[int, List[Tuple[datetime, datetime]]] = defaultdict(list)
        room_booked_times: Dict[int, List[Tuple[datetime, datetime]]] = defaultdict(list)

        for booking in sorted_bookings:
            best_dm = None
            best_room = None
            best_score = -1

            for dm in self.input.dm_profiles:
                if not dm.is_available(booking.start_time, booking.end_time):
                    continue
                if dm.consecutive_work_days >= self.CONSECUTIVE_DAYS_LIMIT:
                    continue
                if booking.script_id:
                    prof = dm.get_proficiency(booking.script_id)
                    if prof < 1:
                        continue
                if self._has_time_conflict(
                    dm_booked_times[dm.dm_id],
                    booking.start_time, booking.end_time
                ):
                    continue

                for room in self.input.rooms:
                    if not room.is_active:
                        continue
                    if booking.player_count > room.capacity:
                        continue
                    if self._has_time_conflict(
                        room_booked_times[room.room_id],
                        booking.start_time, booking.end_time
                    ):
                        continue

                    score = 0
                    if booking.script_id:
                        score += dm.get_proficiency(booking.script_id) * 10
                    score -= dm_workload[dm.dm_id] * 2

                    if score > best_score:
                        best_score = score
                        best_dm = dm
                        best_room = room

            if best_dm and best_room:
                dm_booked_times[best_dm.dm_id].append(
                    (booking.start_time, booking.end_time)
                )
                room_booked_times[best_room.room_id].append(
                    (booking.start_time, booking.end_time)
                )
                dm_workload[best_dm.dm_id] += 1

                self.result.assignments.append(ScheduleAssignment(
                    booking_id=booking.booking_id,
                    dm_id=best_dm.dm_id,
                    room_id=best_room.room_id,
                    script_id=booking.script_id or 0,
                    match_score=best_score,
                    is_new=True,
                ))
            else:
                self.result.unassigned_bookings.append(booking.booking_id)

    def _detect_conflicts(self):
        booked_dm: Dict[int, List[Tuple[datetime, datetime, int]]] = defaultdict(list)
        booked_room: Dict[int, List[Tuple[datetime, datetime, int]]] = defaultdict(list)

        for assignment in self.result.assignments:
            booking = next(
                (b for b in self.input.bookings if b.booking_id == assignment.booking_id),
                None
            )
            if not booking:
                continue

            for start, end, bid in booked_dm[assignment.dm_id]:
                if self._times_overlap(start, end, booking.start_time, booking.end_time):
                    self.result.conflicts.append(ConflictReport(
                        conflict_type='DM_CONFLICT',
                        description=f'DM#{assignment.dm_id} 在预约#{bid}和#{booking.booking_id}时间冲突',
                        booking_id=booking.booking_id,
                        dm_id=assignment.dm_id,
                        severity='error',
                    ))

            for start, end, bid in booked_room[assignment.room_id]:
                if self._times_overlap(start, end, booking.start_time, booking.end_time):
                    self.result.conflicts.append(ConflictReport(
                        conflict_type='ROOM_CONFLICT',
                        description=f'房间#{assignment.room_id} 在预约#{bid}和#{booking.booking_id}时间冲突',
                        booking_id=booking.booking_id,
                        room_id=assignment.room_id,
                        severity='error',
                    ))

            booked_dm[assignment.dm_id].append(
                (booking.start_time, booking.end_time, booking.booking_id)
            )
            booked_room[assignment.room_id].append(
                (booking.start_time, booking.end_time, booking.booking_id)
            )

    @staticmethod
    def _times_overlap(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> bool:
        return s1 < e2 and s2 < e1

    @staticmethod
    def _has_time_conflict(
        booked: List[Tuple[datetime, datetime]],
        start: datetime,
        end: datetime
    ) -> bool:
        for s, e in booked:
            if Scheduler._times_overlap(s, e, start, end):
                return True
        return False

    @staticmethod
    def _check_rest_preference_violation(dm: DMInput, booking: BookingInput) -> bool:
        prefs = dm.rest_preferences
        if not prefs:
            return False

        dt = booking.start_time
        weekday = dt.weekday()
        hour = dt.hour

        if prefs.get('no_weekend_morning'):
            if weekday >= 5 and hour < 12:
                return True

        if prefs.get('no_monday'):
            if weekday == 0:
                return True

        if prefs.get('no_early_shift'):
            if hour < 11:
                return True

        if prefs.get('no_late_shift'):
            end_hour = (dt + timedelta(minutes=booking.duration_minutes)).hour
            if end_hour >= 22:
                return True

        return False


def run_scheduling(input_data: SchedulingInput) -> SchedulingResult:
    scheduler = Scheduler(input_data)
    return scheduler.schedule()


def find_affected_schedules(
    dm_id: int,
    start_date: date,
    end_date: date,
    all_schedules: List[Dict[str, Any]]
) -> List[int]:
    affected = []
    for sched in all_schedules:
        if sched.get('dm_id') == dm_id:
            sched_date = sched.get('date') or sched.get('start_time', datetime.now()).date()
            if start_date <= sched_date <= end_date:
                if not sched.get('is_locked') and sched.get('status') not in ['dm_confirmed', 'in_progress', 'completed']:
                    affected.append(sched.get('id'))
    return affected
