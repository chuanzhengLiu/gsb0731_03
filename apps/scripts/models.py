from django.db import models
from django.utils import timezone


class ScriptType(models.TextChoices):
    REASONING = 'reasoning', '推理'
    EMOTION = 'emotion', '情感'
    MECHANISM = 'mechanism', '机制'
    HORROR = 'horror', '恐怖'
    FACTION = 'faction', '阵营'


class ScriptDifficulty(models.IntegerChoices):
    EASY = 1, '简单'
    MEDIUM = 2, '中等'
    HARD = 3, '困难'
    EXTREME = 4, '极难'


class ScriptStatus(models.TextChoices):
    AVAILABLE = 'available', '可使用'
    MAINTENANCE = 'maintenance', '维护中'
    OFFLINE = 'offline', '已下线'


class Gender(models.TextChoices):
    MALE = 'male', '男'
    FEMALE = 'female', '女'
    ANY = 'any', '不限'


class Script(models.Model):
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='scripts',
        verbose_name='所属门店'
    )
    name = models.CharField(max_length=200, verbose_name='剧本名称')
    type = models.CharField(
        max_length=20,
        choices=ScriptType.choices,
        verbose_name='剧本类型'
    )
    player_count = models.JSONField(
        default=dict,
        verbose_name='玩家人数',
        help_text='格式: {"male": 3, "female": 3, "total": 6}'
    )
    duration_minutes = models.IntegerField(verbose_name='时长(分钟)')
    difficulty = models.IntegerField(
        choices=ScriptDifficulty.choices,
        verbose_name='难度等级'
    )
    status = models.CharField(
        max_length=20,
        choices=ScriptStatus.choices,
        default=ScriptStatus.AVAILABLE,
        verbose_name='状态'
    )
    age_tip = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='年龄提示'
    )
    inventory = models.IntegerField(default=1, verbose_name='库存数量')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='单价(元)'
    )
    description = models.TextField(blank=True, null=True, verbose_name='剧本描述')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'script'
        verbose_name = '剧本'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'

    @property
    def total_players(self):
        return self.player_count.get('total', 0)


class Role(models.Model):
    script = models.ForeignKey(
        Script,
        on_delete=models.CASCADE,
        related_name='roles',
        verbose_name='所属剧本'
    )
    name = models.CharField(max_length=100, verbose_name='角色名称')
    suggested_gender = models.CharField(
        max_length=10,
        choices=Gender.choices,
        default=Gender.ANY,
        verbose_name='建议性别'
    )
    personality_tags = models.JSONField(
        default=list,
        verbose_name='性格标签',
        help_text='格式: ["冷静理智", "情感丰富"]'
    )
    description = models.TextField(blank=True, null=True, verbose_name='角色描述')

    class Meta:
        db_table = 'role'
        verbose_name = '角色'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return f'{self.name} ({self.script.name})'
