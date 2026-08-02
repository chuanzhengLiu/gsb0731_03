from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditAction(models.TextChoices):
    CREATE = 'CREATE', _('创建')
    UPDATE = 'UPDATE', _('更新')
    DELETE = 'DELETE', _('删除')
    LOGIN = 'LOGIN', _('登录')
    LOGOUT = 'LOGOUT', _('登出')
    LOCK = 'LOCK', _('锁定')
    UNLOCK = 'UNLOCK', _('解锁')
    APPROVE = 'APPROVE', _('审批通过')
    REJECT = 'REJECT', _('审批拒绝')
    EXPORT = 'EXPORT', _('导出')
    IMPORT = 'IMPORT', _('导入')
    STATUS_CHANGE = 'STATUS_CHANGE', _('状态变更')


class AuditTargetType(models.TextChoices):
    USER = 'USER', _('用户')
    STORE = 'STORE', _('门店')
    ROOM = 'ROOM', _('房间')
    SCRIPT = 'SCRIPT', _('剧本')
    ROLE = 'ROLE', _('角色')
    DM_PROFILE = 'DM_PROFILE', _('DM资料')
    DM_SKILL = 'DM_SKILL', _('DM技能')
    DM_AVAILABILITY = 'DM_AVAILABILITY', _('DM可用时间')
    DM_LEAVE = 'DM_LEAVE', _('DM请假')
    BOOKING = 'BOOKING', _('预约')
    SCHEDULE = 'SCHEDULE', _('排期')
    AUDIT_LOG = 'AUDIT_LOG', _('审计日志')
    REVIEW = 'REVIEW', _('评价')
    PLAYER_PROFILE = 'PLAYER_PROFILE', _('玩家资料')
    ROLE_ASSIGNMENT = 'ROLE_ASSIGNMENT', _('角色分配')
    OTHER = 'OTHER', _('其他')


class AuditStatus(models.TextChoices):
    SUCCESS = 'SUCCESS', _('成功')
    FAILED = 'FAILED', _('失败')
    PENDING = 'PENDING', _('待处理')


class AuditLog(models.Model):
    id = models.BigAutoField(primary_key=True, verbose_name=_('ID'))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('操作人'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        db_column='user_id',
    )
    username = models.CharField(
        _('用户名（冗余）'),
        max_length=150,
        blank=True,
        default='',
        db_index=True,
    )
    action = models.CharField(
        _('操作类型'),
        max_length=30,
        choices=AuditAction.choices,
        db_index=True,
    )
    target_type = models.CharField(
        _('目标类型'),
        max_length=30,
        choices=AuditTargetType.choices,
        db_index=True,
    )
    target_id = models.BigIntegerField(
        _('目标ID'),
        null=True,
        blank=True,
    )
    target_name = models.CharField(
        _('目标名称（冗余）'),
        max_length=255,
        null=True,
        blank=True,
    )
    store = models.ForeignKey(
        'stores.Store',
        verbose_name=_('所属门店'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        db_column='store_id',
    )
    details = models.JSONField(
        _('操作详情'),
        default=dict,
        blank=True,
    )
    ip_address = models.CharField(
        _('操作IP'),
        max_length=45,
        null=True,
        blank=True,
    )
    user_agent = models.CharField(
        _('浏览器UA'),
        max_length=500,
        null=True,
        blank=True,
    )
    status = models.CharField(
        _('操作状态'),
        max_length=20,
        choices=AuditStatus.choices,
        default=AuditStatus.SUCCESS,
        db_index=True,
    )
    failure_reason = models.CharField(
        _('失败原因'),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(
        _('创建时间'),
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        db_table = 'audit_log'
        verbose_name = _('审计日志')
        verbose_name_plural = _('审计日志')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['action']),
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['store', 'created_at']),
        ]

    def __str__(self):
        return f'{self.username} - {self.get_action_display()} - {self.get_target_type_display()}'
