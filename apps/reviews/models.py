from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Review(models.Model):
    schedule = models.OneToOneField(
        'scheduling.Schedule',
        on_delete=models.CASCADE,
        related_name='review',
        verbose_name='关联排班',
    )
    dm_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        null=True,
        blank=True,
        verbose_name='DM评分(1-5星)',
        help_text='玩家对DM主持人的评分',
    )
    script_rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        null=True,
        blank=True,
        verbose_name='剧本评分(1-5星)',
        help_text='玩家对剧本的评分',
    )
    dm_tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name='DM评价标签',
        help_text='可多选，如: ["沉浸感强","节奏把控好","扶车时机好","准备充分","气氛调节棒"]',
    )
    script_tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name='剧本评价标签',
        help_text='可多选，如: ["剧情精彩","逻辑严密","情感共鸣","机制新颖","角色平衡"]',
    )
    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name='文字评论',
        help_text='玩家的详细文字评价',
    )
    dm_review = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='DM复盘',
        help_text='DM填写的复盘信息，格式见文档',
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_reviews',
        verbose_name='提交人',
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
        db_table = 'reviews'
        verbose_name = '场次评价'
        verbose_name_plural = '场次评价'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['schedule']),
            models.Index(fields=['created_at']),
            models.Index(fields=['dm_rating']),
            models.Index(fields=['script_rating']),
        ]

    def __str__(self):
        return f'评价#{self.id} - 排班#{self.schedule_id}'

    @property
    def has_player_review(self):
        return self.dm_rating is not None or self.script_rating is not None

    @property
    def has_dm_review(self):
        return bool(self.dm_review)

    @property
    def store_id(self):
        return getattr(self.schedule, 'store_id', None)


class ScriptStats(models.Model):
    script = models.OneToOneField(
        'scripts.Script',
        on_delete=models.CASCADE,
        related_name='stats',
        verbose_name='关联剧本',
    )
    avg_dm_rating = models.FloatField(
        default=0.0,
        verbose_name='平均DM评分',
    )
    avg_script_rating = models.FloatField(
        default=0.0,
        verbose_name='平均剧本评分',
    )
    total_sessions = models.IntegerField(
        default=0,
        verbose_name='总场次',
    )
    completed_sessions = models.IntegerField(
        default=0,
        verbose_name='完成场次',
    )
    completion_rate = models.FloatField(
        default=0.0,
        verbose_name='完场率',
        help_text='完场率 = 完成场次 / 总场次',
    )
    complaint_count = models.IntegerField(
        default=0,
        verbose_name='投诉次数',
    )
    turnover_rate = models.FloatField(
        default=0.0,
        verbose_name='月均开本次数',
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name='最后更新时间',
    )

    class Meta:
        db_table = 'script_stats'
        verbose_name = '剧本统计'
        verbose_name_plural = '剧本统计'
        ordering = ['-turnover_rate', '-avg_script_rating']
        indexes = [
            models.Index(fields=['script']),
            models.Index(fields=['turnover_rate']),
            models.Index(fields=['avg_script_rating']),
        ]

    def __str__(self):
        return f'剧本统计#{self.id} - 剧本#{self.script_id}'

    @property
    def overall_rating(self):
        ratings = [r for r in [self.avg_dm_rating, self.avg_script_rating] if r > 0]
        if not ratings:
            return 0.0
        return round(sum(ratings) / len(ratings), 2)

    def update_stats(self):
        from django.apps import apps
        from django.db.models import Avg, Count, Q
        from datetime import timedelta

        Schedule = apps.get_model('scheduling', 'Schedule')
        ScheduleStatus = apps.get_model('scheduling', 'ScheduleStatus')

        script_schedules = Schedule.objects.filter(script_id=self.script_id)

        total = script_schedules.count()
        completed = script_schedules.filter(status=ScheduleStatus.COMPLETED).count()

        self.total_sessions = total
        self.completed_sessions = completed
        self.completion_rate = round((completed / total * 100), 2) if total > 0 else 0.0

        review_qs = Review.objects.filter(
            schedule__script_id=self.script_id,
        )
        dm_ratings = review_qs.exclude(dm_rating__isnull=True).aggregate(
            avg=Avg('dm_rating')
        )['avg']
        script_ratings = review_qs.exclude(script_rating__isnull=True).aggregate(
            avg=Avg('script_rating')
        )['avg']

        self.avg_dm_rating = round(float(dm_ratings), 2) if dm_ratings else 0.0
        self.avg_script_rating = round(float(script_ratings), 2) if script_ratings else 0.0

        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        monthly_sessions = script_schedules.filter(
            created_at__gte=thirty_days_ago
        ).count()
        self.turnover_rate = round(monthly_sessions / 30.0 * 30, 2)

        self.save()
        return self
