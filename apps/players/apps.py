from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PlayersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.players'
    verbose_name = _('玩家管理')
