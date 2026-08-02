from django.db import models
from django.utils import timezone

# 同一 DM/房间两场排班的最小间隔（分钟），低于该值仅提示、不算冲突
MIN_SESSION_GAP_MINUTES = 30


class ScheduleStatus(models.TextChoices):
    ASSIGNED = 'assigned', '已分配'
    DM_CONFIRMED = 'dm_confirmed', 'DM已确认'
    IN_PROGRESS = 'in_progress', '进行中'
    COMPLETED = 'completed', '已完成'
    CANCELLED = 'cancelled', '已取消'


class ConflictType(models.TextChoices):
    DM_CONFLICT = 'dm_conflict', 'DM时间冲突'
    ROOM_CONFLICT = 'room_conflict', '房间时间冲突'
    TIME_OVERLAP = 'time_overlap', '时间重叠'


class Schedule(models.Model):
    booking = models.OneToOneField(
        'bookings.Booking',
        on_delete=models.CASCADE,
        related_name='schedule',
        verbose_name='预约订单',
        null=True,
        blank=True,
    )
    dm = models.ForeignKey(
        'dms.DMProfile',
        on_delete=models.PROTECT,
        related_name='schedules',
        verbose_name='DM主持人',
        null=True,
        blank=True,
    )
    room = models.ForeignKey(
        'stores.Room',
        on_delete=models.PROTECT,
        related_name='schedules',
        verbose_name='房间',
        null=True,
        blank=True,
    )
    script = models.ForeignKey(
        'scripts.Script',
        on_delete=models.PROTECT,
        related_name='schedules',
        verbose_name='剧本',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=30,
        choices=ScheduleStatus.choices,
        default=ScheduleStatus.ASSIGNED,
        verbose_name='排班状态',
        db_index=True,
    )
    actual_start_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='实际开始时间',
    )
    actual_end_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='实际结束时间',
    )
    is_locked = models.BooleanField(
        default=False,
        verbose_name='是否锁定',
        help_text='店长手动锁定后不可被算法修改',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间',
    )

    class Meta:
        db_table = 'schedules'
        verbose_name = '排班'
        verbose_name_plural = '排班'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['dm', 'status']),
            models.Index(fields=['room', 'status']),
        ]

    def __str__(self):
        booking_info = f'预约#{self.booking_id}' if self.booking_id else '未关联预约'
        return f'{booking_info} - {self.get_status_display()}'

    @property
    def scheduled_start_time(self):
        if self.booking_id:
            from django.apps import apps
            from datetime import datetime
            Booking = apps.get_model('bookings', 'Booking')
            try:
                booking = Booking.objects.get(pk=self.booking_id)
                return datetime.combine(booking.date, booking.start_time)
            except Booking.DoesNotExist:
                pass
        return None

    @property
    def scheduled_end_time(self):
        start = self.scheduled_start_time
        if start:
            from datetime import timedelta
            duration = 240
            if self.booking_id:
                from django.apps import apps
                Booking = apps.get_model('bookings', 'Booking')
                try:
                    booking = Booking.objects.get(pk=self.booking_id)
                    duration = booking.duration_minutes
                except Booking.DoesNotExist:
                    pass
            elif self.script_id:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                try:
                    script = Script.objects.get(pk=self.script_id)
                    duration = script.duration_minutes
                except Script.DoesNotExist:
                    pass
            return start + timedelta(minutes=duration)
        return None

    @property
    def scheduled_date(self):
        if self.booking_id:
            from django.apps import apps
            Booking = apps.get_model('bookings', 'Booking')
            try:
                booking = Booking.objects.get(pk=self.booking_id)
                return booking.date
            except Booking.DoesNotExist:
                pass
        return None

    @property
    def player_count(self):
        if self.booking_id:
            from django.apps import apps
            Booking = apps.get_model('bookings', 'Booking')
            try:
                booking = Booking.objects.get(pk=self.booking_id)
                return booking.player_count
            except Booking.DoesNotExist:
                pass
        return 0

    @property
    def store_id(self):
        if self.room_id:
            from django.apps import apps
            Room = apps.get_model('stores', 'Room')
            try:
                room = Room.objects.get(pk=self.room_id)
                return room.store_id
            except Room.DoesNotExist:
                pass
        return None

    def can_modify(self, by_algorithm=True):
        if self.is_locked:
            return False
        if by_algorithm and self.status in [ScheduleStatus.DM_CONFIRMED, ScheduleStatus.IN_PROGRESS, ScheduleStatus.COMPLETED]:
            return False
        if self.status == ScheduleStatus.COMPLETED:
            return False
        return True


class ScheduleConflict(models.Model):
    schedule1 = models.ForeignKey(
        Schedule,
        on_delete=models.CASCADE,
        related_name='conflicts_as_first',
        verbose_name='排班1',
    )
    schedule2 = models.ForeignKey(
        Schedule,
        on_delete=models.CASCADE,
        related_name='conflicts_as_second',
        verbose_name='排班2',
    )
    conflict_type = models.CharField(
        max_length=30,
        choices=ConflictType.choices,
        verbose_name='冲突类型',
        db_index=True,
    )
    description = models.CharField(
        max_length=500,
        verbose_name='冲突描述',
    )
    resolved = models.BooleanField(
        default=False,
        verbose_name='是否已解决',
        db_index=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间',
    )

    class Meta:
        db_table = 'schedule_conflicts'
        verbose_name = '排班冲突'
        verbose_name_plural = '排班冲突'
        ordering = ['-created_at']

    def __str__(self):
        return f'冲突#{self.id}: {self.get_conflict_type_display()}'
