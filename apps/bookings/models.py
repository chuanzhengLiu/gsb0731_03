from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class BookingStatus(models.TextChoices):
    PENDING = 'pending', _('待确认')
    CONFIRMED = 'confirmed', _('已确认')
    IN_PROGRESS = 'in_progress', _('进行中')
    COMPLETED = 'completed', _('已完成')
    CANCELLED = 'cancelled', _('已取消')
    NO_SHOW = 'no_show', _('爽约')


class PlayerGender(models.TextChoices):
    MALE = 'male', _('男')
    FEMALE = 'female', _('女')
    OTHER = 'other', _('其他')


STATUS_TRANSITIONS = {
    BookingStatus.PENDING: [BookingStatus.CONFIRMED, BookingStatus.CANCELLED],
    BookingStatus.CONFIRMED: [BookingStatus.IN_PROGRESS, BookingStatus.CANCELLED],
    BookingStatus.IN_PROGRESS: [BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.NO_SHOW],
    BookingStatus.COMPLETED: [],
    BookingStatus.CANCELLED: [],
    BookingStatus.NO_SHOW: [],
}


def validate_status_transition(current_status, new_status):
    allowed = STATUS_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise ValidationError(
            f'无法从 {current_status.label} 状态变更为 {new_status.label} 状态'
        )


class Booking(models.Model):
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='bookings',
        verbose_name=_('所属门店')
    )
    date = models.DateField(verbose_name=_('预约日期'))
    start_time = models.TimeField(verbose_name=_('开始时间'))
    duration_minutes = models.IntegerField(
        default=240,
        verbose_name=_('时长(分钟)')
    )
    player_count = models.IntegerField(verbose_name=_('玩家人数'))
    preferences = models.JSONField(
        default=dict,
        verbose_name=_('偏好设置'),
        help_text=_(
            '格式: {"preferred_types": [], "difficulty_preference": int, '
            '"is_newbie": bool, "player_notes": str}'
        )
    )
    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
        verbose_name=_('预约状态')
    )
    customer_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('客户姓名')
    )
    customer_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_('客户电话')
    )
    deposit_amount = models.FloatField(
        default=0,
        verbose_name=_('订金金额')
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_bookings',
        verbose_name=_('创建人')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('创建时间')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('更新时间')
    )

    class Meta:
        db_table = 'bookings'
        verbose_name = _('预约')
        verbose_name_plural = _('预约')
        ordering = ['-date', '-start_time']
        indexes = [
            models.Index(fields=['store', 'date', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return f'{self.date} {self.start_time} - {self.store.name} ({self.get_status_display()})'

    def clean(self):
        super().clean()
        if self.player_count <= 0:
            raise ValidationError({'player_count': '玩家人数必须大于0'})
        if self.duration_minutes <= 0:
            raise ValidationError({'duration_minutes': '时长必须大于0'})
        if self.deposit_amount < 0:
            raise ValidationError({'deposit_amount': '订金金额不能为负数'})

    def can_transition_to(self, new_status):
        return new_status in STATUS_TRANSITIONS.get(self.status, [])

    def transition_to(self, new_status):
        validate_status_transition(self.status, new_status)
        self.status = new_status
        self.save()

    @property
    def end_time(self):
        from datetime import datetime, timedelta
        start = datetime.combine(self.date, self.start_time)
        end = start + timedelta(minutes=self.duration_minutes)
        return end.time()

    @property
    def scheduled_start(self):
        from datetime import datetime
        return datetime.combine(self.date, self.start_time)

    @property
    def scheduled_end(self):
        from datetime import timedelta
        return self.scheduled_start + timedelta(minutes=self.duration_minutes)

    def has_conflict_with(self, other_booking):
        if self.store_id != other_booking.store_id:
            return False
        if self.date != other_booking.date:
            return False
        from datetime import datetime, timedelta
        self_start = datetime.combine(self.date, self.start_time)
        self_end = self_start + timedelta(minutes=self.duration_minutes)
        other_start = datetime.combine(other_booking.date, other_booking.start_time)
        other_end = other_start + timedelta(minutes=other_booking.duration_minutes)
        return self_start < other_end and other_start < self_end


class BookingPlayer(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name='players',
        verbose_name=_('所属预约')
    )
    name = models.CharField(max_length=100, verbose_name=_('玩家姓名'))
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_('联系电话')
    )
    gender = models.CharField(
        max_length=10,
        choices=PlayerGender.choices,
        blank=True,
        null=True,
        verbose_name=_('性别')
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_('标签'),
        help_text=_('格式: ["标签1", "标签2"]')
    )
    horror_tolerance = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_('恐怖耐受度'),
        help_text=_('0-3: 0=完全不能, 1=轻微, 2=中等, 3=很高')
    )
    accept_reverse = models.BooleanField(
        default=False,
        verbose_name=_('接受反串')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('创建时间')
    )

    class Meta:
        db_table = 'booking_players'
        verbose_name = _('预约玩家')
        verbose_name_plural = _('预约玩家')
        ordering = ['id']

    def __str__(self):
        gender_display = self.get_gender_display() if self.gender else '未设置'
        return f'{self.name} ({gender_display})'

    def clean(self):
        super().clean()
        if self.horror_tolerance is not None:
            if self.horror_tolerance < 0 or self.horror_tolerance > 3:
                raise ValidationError({'horror_tolerance': '恐怖耐受度必须在0-3之间'})
