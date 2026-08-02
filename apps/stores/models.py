from django.conf import settings
from django.db import models


class Store(models.Model):
    name = models.CharField(max_length=200, verbose_name='门店名称')
    address = models.CharField(max_length=500, verbose_name='门店地址')
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_stores',
        verbose_name='门店管理员'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'stores'
        verbose_name = '门店'
        verbose_name_plural = '门店'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Room(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='rooms',
        verbose_name='所属门店'
    )
    name = models.CharField(max_length=100, verbose_name='房间名称')
    capacity = models.PositiveIntegerField(verbose_name='容纳人数')
    has_props = models.BooleanField(default=False, verbose_name='是否有道具')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'rooms'
        verbose_name = '房间'
        verbose_name_plural = '房间'
        ordering = ['store', 'name']
        unique_together = ['store', 'name']

    def __str__(self):
        return f'{self.store.name} - {self.name}'
