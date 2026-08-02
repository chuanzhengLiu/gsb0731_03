from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User, UserRole
from apps.stores.models import Store


class Command(BaseCommand):
    help = '创建初始超级用户和示例数据：platform_admin账号、示例门店、store_manager账号'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='如果用户已存在则重置密码',
        )
        parser.add_argument(
            '--admin-username',
            type=str,
            default='admin',
            help='平台管理员用户名 (默认: admin)',
        )
        parser.add_argument(
            '--admin-password',
            type=str,
            default='admin123456',
            help='平台管理员密码 (默认: admin123456)',
        )
        parser.add_argument(
            '--manager-username',
            type=str,
            default='manager1',
            help='门店经理用户名 (默认: manager1)',
        )
        parser.add_argument(
            '--manager-password',
            type=str,
            default='manager123',
            help='门店经理密码 (默认: manager123)',
        )
        parser.add_argument(
            '--store-name',
            type=str,
            default='示例旗舰店',
            help='示例门店名称 (默认: 示例旗舰店)',
        )
        parser.add_argument(
            '--store-address',
            type=str,
            default='北京市朝阳区示例路123号',
            help='示例门店地址 (默认: 北京市朝阳区示例路123号)',
        )

    def handle(self, *args, **options):
        force = options['force']
        admin_username = options['admin_username']
        admin_password = options['admin_password']
        manager_username = options['manager_username']
        manager_password = options['manager_password']
        store_name = options['store_name']
        store_address = options['store_address']

        try:
            with transaction.atomic():
                self.stdout.write(self.style.MIGRATE_HEADING('开始初始化初始数据...'))

                platform_admin, admin_created = self._create_or_update_user(
                    username=admin_username,
                    password=admin_password,
                    role=UserRole.PLATFORM_ADMIN,
                    name='平台管理员',
                    force=force,
                    is_superuser=True,
                    is_staff=True,
                )

                if admin_created:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ 平台管理员创建成功: {admin_username} / {admin_password}'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠ 平台管理员已存在: {admin_username}'
                            + (' (密码已重置)' if force else '')
                        )
                    )

                store, store_created = self._create_or_update_store(
                    name=store_name,
                    address=store_address,
                    admin=platform_admin,
                )

                if store_created:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ 示例门店创建成功: {store_name} (ID: {store.id})'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'⚠ 示例门店已存在: {store_name} (ID: {store.id})')
                    )

                store_manager, manager_created = self._create_or_update_user(
                    username=manager_username,
                    password=manager_password,
                    role=UserRole.STORE_MANAGER,
                    name='门店经理',
                    store=store,
                    force=force,
                    is_staff=True,
                )

                if not store.admin_id:
                    store.admin = store_manager
                    store.save(update_fields=['admin'])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ 门店管理员已设置: {manager_username}'
                        )
                    )

                if manager_created:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ 门店经理创建成功: {manager_username} / {manager_password}'
                            f' (门店: {store_name})'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠ 门店经理已存在: {manager_username}'
                            + (' (密码已重置)' if force else '')
                            + f' (门店: {store_name})'
                        )
                    )

                self.stdout.write('')
                self.stdout.write(self.style.MIGRATE_HEADING('初始化完成！'))
                self.stdout.write(
                    self.style.SQL_TABLE(
                        f'\n登录信息:\n'
                        f'  平台管理员: {admin_username} / {admin_password}\n'
                        f'  门店经理:   {manager_username} / {manager_password}\n'
                        f'\n门店信息:\n'
                        f'  门店名称: {store_name}\n'
                        f'  门店地址: {store_address}\n'
                        f'  门店ID:   {store.id}'
                    )
                )

        except Exception as e:
            raise CommandError(f'初始化失败: {e}')

    def _create_or_update_user(
        self,
        username,
        password,
        role,
        name='',
        store=None,
        force=False,
        is_superuser=False,
        is_staff=False,
    ):
        try:
            user = User.objects.get(username=username)
            if force:
                user.set_password(password)
                user.role = role
                user.name = name or user.name
                if store is not None:
                    user.store = store
                user.is_superuser = is_superuser
                user.is_staff = is_staff
                user.save(
                    update_fields=[
                        'password', 'role', 'name', 'store',
                        'is_superuser', 'is_staff',
                    ]
                )
                return user, False
            return user, False
        except User.DoesNotExist:
            user = User.objects.create_user(
                username=username,
                password=password,
                role=role,
                name=name,
                store=store,
                is_superuser=is_superuser,
                is_staff=is_staff,
                is_active=True,
            )
            return user, True

    def _create_or_update_store(self, name, address, admin=None):
        try:
            store = Store.objects.get(name=name)
            updated = False
            if store.address != address:
                store.address = address
                updated = True
            if admin is not None and not store.admin_id:
                store.admin = admin
                updated = True
            if updated:
                store.save()
            return store, False
        except Store.DoesNotExist:
            store = Store.objects.create(
                name=name,
                address=address,
                admin=admin,
            )
            return store, True
