from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class UserRole(models.TextChoices):
    PLATFORM_ADMIN = 'platform_admin', _('平台管理员')
    STORE_MANAGER = 'store_manager', _('门店经理')
    ASSISTANT_MANAGER = 'assistant_manager', _('副经理')
    DM = 'dm', _('DM主持人')
    FRONT_DESK = 'front_desk', _('前台')
    PLAYER = 'player', _('玩家')


ROLE_HIERARCHY = {
    UserRole.PLATFORM_ADMIN: 100,
    UserRole.STORE_MANAGER: 80,
    UserRole.ASSISTANT_MANAGER: 60,
    UserRole.DM: 40,
    UserRole.FRONT_DESK: 30,
    UserRole.PLAYER: 10,
}


class User(AbstractUser):
    id = models.BigAutoField(primary_key=True)
    username = models.CharField(
        _('用户名'),
        max_length=150,
        unique=True,
        error_messages={
            'unique': _('该用户名已被使用'),
        },
    )
    password = models.CharField(_('密码'), max_length=128)
    name = models.CharField(_('真实姓名'), max_length=100, blank=True, default='')
    role = models.CharField(
        _('角色'),
        max_length=30,
        choices=UserRole.choices,
        default=UserRole.PLAYER,
    )
    store = models.ForeignKey(
        'stores.Store',
        verbose_name=_('所属门店'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        db_column='store_id',
    )
    phone = models.CharField(
        _('手机号'),
        max_length=20,
        blank=True,
        default='',
        db_index=True,
    )
    first_login = models.BooleanField(_('是否首次登录'), default=True)
    is_active = models.BooleanField(_('是否启用'), default=True)
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'accounts_user'
        verbose_name = _('用户')
        verbose_name_plural = _('用户')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['store', 'role']),
        ]

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    @property
    def role_level(self):
        return ROLE_HIERARCHY.get(self.role, 0)

    def has_role_or_above(self, role):
        return self.role_level >= ROLE_HIERARCHY.get(role, 999)

    def is_platform_admin(self):
        return self.role == UserRole.PLATFORM_ADMIN

    def is_store_manager(self):
        return self.role == UserRole.STORE_MANAGER

    def is_dm(self):
        return self.role == UserRole.DM

    def is_front_desk(self):
        return self.role == UserRole.FRONT_DESK

    def is_player(self):
        return self.role == UserRole.PLAYER

    def belongs_to_store(self, store_id):
        if self.is_platform_admin():
            return True
        return self.store_id == store_id
