from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class DMProfile(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='dm_profile',
        verbose_name='关联用户'
    )
    join_date = models.DateField(
        verbose_name='入职日期',
        default=timezone.now
    )
    specialty_types = models.JSONField(
        default=list,
        verbose_name='擅长类型',
        help_text='格式: ["推理", "情感", "机制"]'
    )
    total_sessions = models.IntegerField(
        default=0,
        verbose_name='总带本场次'
    )
    avg_rating = models.FloatField(
        default=0.0,
        verbose_name='平均评分'
    )
    consecutive_days = models.IntegerField(
        default=0,
        verbose_name='连续工作天数'
    )
    fatigue_warning = models.BooleanField(
        default=False,
        verbose_name='疲劳预警'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )

    class Meta:
        db_table = 'dm_profile'
        verbose_name = 'DM主持人档案'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['join_date']),
            models.Index(fields=['fatigue_warning']),
        ]

    def __str__(self):
        return f'{self.user.name} ({self.user.username}) - DM档案'

    @property
    def store_id(self):
        return self.user.store_id

    @property
    def store(self):
        return self.user.store

    def update_consecutive_days(self):
        from datetime import timedelta
        from django.db.models import F
        from django.apps import apps

        today = timezone.now().date()
        consecutive = 0

        try:
            Schedule = apps.get_model('scheduling', 'Schedule')
            Booking = apps.get_model('bookings', 'Booking')

            valid_statuses = ['assigned', 'dm_confirmed', 'in_progress', 'completed']

            schedule_dates = set(
                Schedule.objects.filter(
                    dm_id=self.id,
                    status__in=valid_statuses
                ).exclude(
                    booking__isnull=True
                ).values_list('booking__date', flat=True)
            )

            check_date = today
            while check_date in schedule_dates:
                consecutive += 1
                check_date -= timedelta(days=1)

            self.consecutive_days = consecutive
        except Exception as e:
            pass

        if self.consecutive_days >= 5:
            self.fatigue_warning = True
        elif self.consecutive_days >= 3:
            self.fatigue_warning = True
        else:
            self.fatigue_warning = False

        self.save(update_fields=['consecutive_days', 'fatigue_warning'])
        return self.consecutive_days

    def is_critically_fatigued(self):
        return self.consecutive_days >= 5

    def get_workload_stats(self, month_date=None):
        from django.apps import apps
        from django.db.models import Sum, Count, Q
        from datetime import datetime, timedelta

        if month_date is None:
            month_date = timezone.now().date()

        first_day = month_date.replace(day=1)
        if first_day.month == 12:
            last_day = first_day.replace(year=first_day.year + 1, month=1) - timedelta(days=1)
        else:
            last_day = first_day.replace(month=first_day.month + 1) - timedelta(days=1)

        Schedule = apps.get_model('scheduling', 'Schedule')
        Booking = apps.get_model('bookings', 'Booking')

        qs = Schedule.objects.filter(
            dm_id=self.id,
            booking__date__gte=first_day,
            booking__date__lte=last_day,
            status__in=['assigned', 'dm_confirmed', 'in_progress', 'completed']
        )

        session_count = qs.count()
        total_minutes = 0

        for sch in qs.select_related('booking', 'script'):
            if sch.booking_id:
                total_minutes += sch.booking.duration_minutes
            elif sch.script_id:
                total_minutes += sch.script.duration_minutes
            else:
                total_minutes += 240

        return {
            'current_month_sessions': session_count,
            'current_month_total_minutes': total_minutes,
            'consecutive_days': self.consecutive_days,
            'total_sessions_career': self.total_sessions,
            'avg_rating': self.avg_rating,
            'fatigue_level': (
                'critical' if self.consecutive_days >= 5
                else 'warning' if self.consecutive_days >= 3
                else 'normal' if self.consecutive_days >= 1
                else 'good'
            ),
            'fatigue_warning': self.fatigue_warning,
        }


class DMSkill(models.Model):
    id = models.BigAutoField(primary_key=True)
    dm = models.ForeignKey(
        DMProfile,
        on_delete=models.CASCADE,
        related_name='skills',
        verbose_name='DM主持人'
    )
    script = models.ForeignKey(
        'scripts.Script',
        on_delete=models.CASCADE,
        related_name='dm_skills',
        verbose_name='剧本'
    )
    proficiency = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='熟练度(1-5星)'
    )
    play_count = models.IntegerField(
        default=0,
        verbose_name='带本次数'
    )
    last_played = models.DateField(
        null=True,
        blank=True,
        verbose_name='上次带本日期'
    )

    class Meta:
        db_table = 'dm_skill'
        verbose_name = 'DM技能熟练度'
        verbose_name_plural = verbose_name
        ordering = ['dm', '-proficiency', '-play_count']
        unique_together = ['dm', 'script']
        indexes = [
            models.Index(fields=['dm']),
            models.Index(fields=['script']),
            models.Index(fields=['proficiency']),
        ]

    def __str__(self):
        return f'{self.dm.user.name} - {self.script.name} ({self.proficiency}星)'


class DMAvailability(models.Model):
    DAY_CHOICES = [
        (0, '周一'),
        (1, '周二'),
        (2, '周三'),
        (3, '周四'),
        (4, '周五'),
        (5, '周六'),
        (6, '周日'),
    ]

    id = models.BigAutoField(primary_key=True)
    dm = models.ForeignKey(
        DMProfile,
        on_delete=models.CASCADE,
        related_name='availabilities',
        verbose_name='DM主持人'
    )
    day_of_week = models.IntegerField(
        choices=DAY_CHOICES,
        verbose_name='星期几'
    )
    start_time = models.TimeField(
        verbose_name='开始时间'
    )
    end_time = models.TimeField(
        verbose_name='结束时间'
    )
    is_recurring = models.BooleanField(
        default=True,
        verbose_name='是否循环'
    )
    specific_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='指定日期(非循环时设置)'
    )
    is_unavailable = models.BooleanField(
        default=False,
        verbose_name='标记临时不可用'
    )
    note = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name='备注'
    )

    class Meta:
        db_table = 'dm_availability'
        verbose_name = 'DM可用时间'
        verbose_name_plural = verbose_name
        ordering = ['dm', 'day_of_week', 'start_time']
        indexes = [
            models.Index(fields=['dm']),
            models.Index(fields=['day_of_week']),
            models.Index(fields=['specific_date']),
            models.Index(fields=['is_unavailable']),
        ]

    def __str__(self):
        day_display = self.get_day_of_week_display()
        if not self.is_recurring and self.specific_date:
            return f'{self.dm.user.name} - {self.specific_date} {self.start_time}-{self.end_time}'
        return f'{self.dm.user.name} - {day_display} {self.start_time}-{self.end_time}'


class DMTemporaryUnavailable(models.Model):
    id = models.BigAutoField(primary_key=True)
    dm = models.ForeignKey(
        DMProfile,
        on_delete=models.CASCADE,
        related_name='temporary_unavailables',
        verbose_name='DM主持人'
    )
    start_date = models.DateField(
        verbose_name='开始日期'
    )
    end_date = models.DateField(
        verbose_name='结束日期'
    )
    reason = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name='请假原因'
    )
    is_approved = models.BooleanField(
        default=False,
        verbose_name='是否已批准'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )

    class Meta:
        db_table = 'dm_temporary_unavailable'
        verbose_name = 'DM临时不可用/请假'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['dm']),
            models.Index(fields=['start_date', 'end_date']),
            models.Index(fields=['is_approved']),
        ]

    def __str__(self):
        status = '已批准' if self.is_approved else '待审批'
        return f'{self.dm.user.name} - {self.start_date}至{self.end_date} ({status})'
