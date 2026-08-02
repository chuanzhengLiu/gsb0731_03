from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


PREFERENCE_TAGS = [
    '推理型', '情感型', '活跃型', '沉浸型',
    '搞笑型', '领导型', '辅助型', '新手型', '老玩家型',
]


PERSONALITY_TAG_VOCABULARY = [
    '冷静理智', '情感丰富', '搞笑担当', '领导力强', '逻辑推理',
    '社交活跃', '细腻敏感', '沉默寡言', '冒险精神', '团队协作',
]


def validate_preference_tags(value):
    if not isinstance(value, list):
        raise ValidationError('偏好标签必须是数组格式')
    for tag in value:
        if tag not in PREFERENCE_TAGS:
            raise ValidationError(f'无效的偏好标签: {tag}')


def validate_horror_tolerance(value):
    if value is not None and (value < 0 or value > 3):
        raise ValidationError('恐怖耐受度必须在0-3之间')


def validate_history_roles(value):
    if not isinstance(value, list):
        raise ValidationError('历史角色必须是数组格式')
    for idx, role in enumerate(value):
        if not isinstance(role, dict):
            raise ValidationError(f'第{idx + 1}条历史角色必须是字典格式')
        required_fields = ['script_id', 'role_id', 'role_name']
        for field in required_fields:
            if field not in role:
                raise ValidationError(f'第{idx + 1}条历史角色缺少必填字段: {field}')


class PlayerProfile(models.Model):
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        verbose_name=_('手机号'),
        help_text=_('匿名玩家可为空'),
        db_index=True,
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_('玩家姓名'),
        help_text=_('匿名玩家必填'),
    )
    preference_tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('偏好标签'),
        validators=[validate_preference_tags],
        help_text=_(
            '格式: ["推理型", "情感型", "活跃型", "沉浸型", '
            '"搞笑型", "领导型", "辅助型", "新手型", "老玩家型"]'
        ),
    )
    horror_tolerance = models.IntegerField(
        default=0,
        blank=True,
        verbose_name=_('恐怖耐受度'),
        validators=[validate_horror_tolerance],
        help_text=_('0=完全不能接受, 1=轻微, 2=中等, 3=非常喜欢'),
    )
    accept_reverse = models.BooleanField(
        default=False,
        verbose_name=_('是否接受反串'),
    )
    history_roles = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('历史角色记录'),
        validators=[validate_history_roles],
        help_text=_(
            '格式: [{"script_id": int, "role_id": int, "role_name": str, '
            '"satisfaction": int, "date": "YYYY-MM-DD"}]'
        ),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('创建时间'),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('更新时间'),
    )

    class Meta:
        db_table = 'player_profiles'
        verbose_name = _('玩家档案')
        verbose_name_plural = _('玩家档案')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        identifier = self.phone or f'匿名-{self.id}'
        name_part = f' ({self.name})' if self.name else ''
        return f'{identifier}{name_part}'

    def clean(self):
        super().clean()
        if not self.phone and not self.name:
            raise ValidationError({
                'phone': '匿名玩家必须填写姓名',
                'name': '匿名玩家必须填写姓名',
            })

    @property
    def total_plays(self):
        return len(self.history_roles)

    @property
    def last_visit_date(self):
        if not self.history_roles:
            return None
        dates = [r.get('date') for r in self.history_roles if r.get('date')]
        if not dates:
            return None
        return max(dates)

    @property
    def avg_satisfaction(self):
        if not self.history_roles:
            return None
        scores = [r.get('satisfaction') for r in self.history_roles if r.get('satisfaction')]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 1)

    def add_history_role(self, script_id, role_id, role_name, satisfaction=None, date=None):
        entry = {
            'script_id': script_id,
            'role_id': role_id,
            'role_name': role_name,
        }
        if satisfaction is not None:
            entry['satisfaction'] = satisfaction
        if date is not None:
            entry['date'] = date.isoformat() if hasattr(date, 'isoformat') else str(date)
        else:
            entry['date'] = timezone.now().date().isoformat()
        self.history_roles.append(entry)
        self.save(update_fields=['history_roles', 'updated_at'])


class RoleAssignment(models.Model):
    schedule = models.ForeignKey(
        'scheduling.Schedule',
        on_delete=models.CASCADE,
        related_name='role_assignments',
        verbose_name=_('所属场次'),
    )
    player_profile = models.ForeignKey(
        PlayerProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='role_assignments',
        verbose_name=_('关联玩家档案'),
    )
    player_name = models.CharField(
        max_length=100,
        verbose_name=_('玩家姓名'),
        help_text=_('即使匿名也填写'),
    )
    player_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_('玩家电话'),
    )
    role = models.ForeignKey(
        'scripts.Role',
        on_delete=models.PROTECT,
        related_name='assignments',
        verbose_name=_('分配角色'),
    )
    match_score = models.FloatField(
        default=0.0,
        verbose_name=_('系统匹配度'),
        help_text=_('0-100分'),
    )
    is_manual_adjusted = models.BooleanField(
        default=False,
        verbose_name=_('是否DM手动调整'),
    )
    satisfaction = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_('事后满意度'),
        help_text=_('1-5星'),
    )
    assigned_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_('分配时间'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('创建时间'),
    )

    class Meta:
        db_table = 'role_assignments'
        verbose_name = _('角色分配')
        verbose_name_plural = _('角色分配')
        ordering = ['schedule', 'id']
        indexes = [
            models.Index(fields=['schedule']),
            models.Index(fields=['player_profile']),
            models.Index(fields=['role']),
            models.Index(fields=['assigned_at']),
        ]
        unique_together = [
            ['schedule', 'role'],
        ]

    def __str__(self):
        return f'{self.player_name} - {self.role.name} (场次#{self.schedule_id})'

    def clean(self):
        super().clean()
        if self.satisfaction is not None:
            if self.satisfaction < 1 or self.satisfaction > 5:
                raise ValidationError({'satisfaction': '满意度必须在1-5之间'})
        if self.match_score < 0 or self.match_score > 100:
            raise ValidationError({'match_score': '匹配度必须在0-100之间'})
