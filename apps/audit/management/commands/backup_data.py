import csv
import glob
import json
import os
from datetime import datetime, timedelta

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone


DEFAULT_BACKUP_DIR = getattr(settings, 'BACKUP_DIR', None)
DEFAULT_RETENTION_DAYS = 30


class Command(BaseCommand):
    help = '每日数据备份：导出所有表数据到CSV存到BACKUP_DIR，保留最近N天备份'

    def add_arguments(self, parser):
        parser.add_argument(
            '--backup-dir',
            type=str,
            default=str(DEFAULT_BACKUP_DIR) if DEFAULT_BACKUP_DIR else None,
            help=f'备份目录 (默认: {DEFAULT_BACKUP_DIR})',
        )
        parser.add_argument(
            '--retention-days',
            type=int,
            default=DEFAULT_RETENTION_DAYS,
            help=f'保留备份的天数 (默认: {DEFAULT_RETENTION_DAYS}天)',
        )
        parser.add_argument(
            '--include-apps',
            type=str,
            nargs='*',
            help='只备份指定的app（例如：accounts stores bookings）',
        )
        parser.add_argument(
            '--exclude-apps',
            type=str,
            nargs='*',
            default=['admin', 'auth', 'contenttypes', 'sessions', 'messages', 'staticfiles'],
            help='排除的app (默认排除Django内置app)',
        )
        parser.add_argument(
            '--include-models',
            type=str,
            nargs='*',
            help='只备份指定的模型（格式：app_label.model_name，例如 accounts.User）',
        )
        parser.add_argument(
            '--exclude-models',
            type=str,
            nargs='*',
            default=['audit.AuditLog'],
            help='排除的模型（格式：app_label.model_name）',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='分批导出的批次大小 (默认: 1000)',
        )
        parser.add_argument(
            '--no-cleanup',
            action='store_true',
            help='不清理过期备份',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='只显示将要备份的内容，不实际执行',
        )

    def handle(self, *args, **options):
        backup_dir = options['backup_dir']
        retention_days = options['retention_days']
        include_apps = options['include_apps']
        exclude_apps = set(options['exclude_apps'] or [])
        include_models = options['include_models']
        exclude_models = set(options['exclude_models'] or [])
        batch_size = options['batch_size']
        no_cleanup = options['no_cleanup']
        dry_run = options['dry_run']

        if not backup_dir:
            raise CommandError(
                '未指定备份目录。请设置 settings.BACKUP_DIR 或使用 --backup-dir 参数。'
            )

        backup_dir = os.path.abspath(backup_dir)

        if dry_run:
            self.stdout.write(self.style.WARNING('⚠ DRY RUN 模式 - 不会实际创建文件'))

        try:
            timestamp = timezone.now()
            date_str = timestamp.strftime('%Y%m%d')
            datetime_str = timestamp.strftime('%Y%m%d_%H%M%S')

            daily_backup_dir = os.path.join(backup_dir, date_str)
            metadata_file = os.path.join(daily_backup_dir, f'backup_metadata_{datetime_str}.json')

            self.stdout.write(self.style.MIGRATE_HEADING(f'开始数据备份...'))
            self.stdout.write(f'  备份目录: {backup_dir}')
            self.stdout.write(f'  时间戳: {datetime_str}')
            self.stdout.write(f'  保留天数: {retention_days}天')

            if not dry_run:
                os.makedirs(daily_backup_dir, exist_ok=True)

            models_to_backup = self._get_models_to_backup(
                include_apps=include_apps,
                exclude_apps=exclude_apps,
                include_models=include_models,
                exclude_models=exclude_models,
            )

            if not models_to_backup:
                self.stdout.write(self.style.WARNING('⚠ 没有找到需要备份的模型'))
                return

            self.stdout.write('')
            self.stdout.write(f'找到 {len(models_to_backup)} 个模型需要备份:')
            for model in models_to_backup:
                self.stdout.write(f'  - {model._meta.app_label}.{model.__name__}')

            backup_summary = {
                'timestamp': timestamp.isoformat(),
                'backup_dir': daily_backup_dir,
                'datetime_str': datetime_str,
                'models': [],
                'total_rows': 0,
            }

            total_rows = 0

            for model in models_to_backup:
                app_label = model._meta.app_label
                model_name = model.__name__
                model_key = f'{app_label}.{model_name}'

                self.stdout.write('')
                self.stdout.write(
                    self.style.SQL_FIELD(
                        f'备份 {app_label}.{model_name}...'
                    )
                )

                filename = f'{app_label}_{model_name}_{datetime_str}.csv'
                filepath = os.path.join(daily_backup_dir, filename)

                row_count = 0
                model_info = {
                    'model': model_key,
                    'file': filename,
                    'rows': 0,
                }

                try:
                    queryset = model.objects.all()
                    total_count = queryset.count()
                    model_info['rows_total'] = total_count

                    fields = self._get_model_fields(model)
                    field_names = [f.name for f in fields]

                    if dry_run:
                        self.stdout.write(
                            f'  [DRY RUN] 将导出 {total_count} 行，'
                            f'{len(field_names)} 列到 {filename}'
                        )
                        row_count = total_count
                    else:
                        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow(field_names)

                            if total_count == 0:
                                self.stdout.write(
                                    self.style.WARNING(f'  模型无数据，跳过 (创建空文件)')
                                )
                            else:
                                if total_count <= batch_size:
                                    for obj in queryset.iterator(chunk_size=batch_size):
                                        row = self._object_to_row(obj, fields)
                                        writer.writerow(row)
                                        row_count += 1
                                else:
                                    for start in range(0, total_count, batch_size):
                                        batch = queryset[start:start + batch_size]
                                        for obj in batch:
                                            row = self._object_to_row(obj, fields)
                                            writer.writerow(row)
                                            row_count += 1
                                        progress = min(start + batch_size, total_count)
                                        self.stdout.write(
                                            f'  进度: {progress}/{total_count} '
                                            f'({100 * progress // total_count}%)'
                                        )

                    model_info['rows_exported'] = row_count
                    total_rows += row_count

                    if not dry_run:
                        file_size = os.path.getsize(filepath)
                        model_info['file_size_bytes'] = file_size
                        model_info['file_size_human'] = self._format_file_size(file_size)

                    if row_count == total_count:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✓ 完成: {row_count} 行'
                                + (f' ({model_info.get("file_size_human", "")})'
                                   if not dry_run else '')
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f'  ✗ 不完整: 导出{row_count}/{total_count} 行'
                            )
                        )

                except Exception as e:
                    model_info['error'] = str(e)
                    self.stdout.write(
                        self.style.ERROR(f'  ✗ 备份失败: {e}')
                    )

                backup_summary['models'].append(model_info)

            backup_summary['total_rows'] = total_rows

            if not dry_run:
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(backup_summary, f, ensure_ascii=False, indent=2, default=str)

            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING('备份摘要'))
            self.stdout.write(f'  备份模型数: {len(backup_summary["models"])}')
            self.stdout.write(f'  总数据行数: {total_rows}')
            if not dry_run:
                self.stdout.write(f'  元数据文件: {metadata_file}')

            if not no_cleanup and not dry_run:
                self.stdout.write('')
                self._cleanup_old_backups(backup_dir, retention_days)

            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✓ 数据备份完成！'))

        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f'备份失败: {e}')

    def _get_models_to_backup(self, include_apps, exclude_apps, include_models, exclude_models):
        models_list = []

        if include_models:
            for model_spec in include_models:
                try:
                    if '.' in model_spec:
                        app_label, model_name = model_spec.rsplit('.', 1)
                        model = apps.get_model(app_label, model_name)
                        models_list.append(model)
                except (LookupError, ValueError) as e:
                    self.stdout.write(
                        self.style.ERROR(f'  跳过无效模型 {model_spec}: {e}')
                    )
            return models_list

        for model in apps.get_models():
            app_label = model._meta.app_label
            model_name = model.__name__
            model_key = f'{app_label}.{model_name}'

            if include_apps and app_label not in include_apps:
                continue

            if app_label in exclude_apps:
                continue

            if model_key in exclude_models:
                continue

            models_list.append(model)

        return sorted(models_list, key=lambda m: (m._meta.app_label, m.__name__))

    def _get_model_fields(self, model):
        fields = []
        for field in model._meta.get_fields():
            if isinstance(field, (models.ManyToManyField, models.ManyToOneRel,
                                  models.ManyToManyRel, models.OneToOneRel)):
                continue
            if isinstance(field, models.ForeignKey):
                fields.append(field)
                fk_id_field = next(
                    (f for f in model._meta.get_fields()
                     if isinstance(f, models.ForeignKey) and f.attname == field.attname),
                    None
                )
            else:
                fields.append(field)
        return fields

    def _object_to_row(self, obj, fields):
        row = []
        for field in fields:
            try:
                value = getattr(obj, field.attname, None)
            except AttributeError:
                value = getattr(obj, field.name, None)

            if value is None:
                row.append('')
            elif isinstance(value, datetime):
                row.append(value.strftime('%Y-%m-%d %H:%M:%S'))
            elif isinstance(value, (dict, list)):
                try:
                    row.append(json.dumps(value, ensure_ascii=False))
                except (TypeError, ValueError):
                    row.append(str(value))
            elif isinstance(value, bytes):
                try:
                    row.append(value.decode('utf-8'))
                except UnicodeDecodeError:
                    row.append(value.hex())
            else:
                row.append(str(value))
        return row

    def _format_file_size(self, size_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f'{size_bytes:.2f} {unit}'
            size_bytes /= 1024.0
        return f'{size_bytes:.2f} TB'

    def _cleanup_old_backups(self, backup_dir, retention_days):
        self.stdout.write(self.style.MIGRATE_HEADING(f'清理超过 {retention_days} 天的旧备份...'))

        cutoff_date = timezone.now() - timedelta(days=retention_days)
        cutoff_date_str = cutoff_date.strftime('%Y%m%d')

        if not os.path.exists(backup_dir):
            self.stdout.write(self.style.WARNING('  备份目录不存在，跳过清理'))
            return

        cleaned_count = 0
        total_freed_size = 0

        date_dirs = sorted(
            [d for d in os.listdir(backup_dir)
             if os.path.isdir(os.path.join(backup_dir, d)) and d.isdigit()],
            reverse=True,
        )

        for date_dir_name in date_dirs:
            try:
                dir_date_str = date_dir_name
                if dir_date_str < cutoff_date_str:
                    dir_path = os.path.join(backup_dir, date_dir_name)

                    dir_size = self._get_dir_size(dir_path)

                    import shutil
                    shutil.rmtree(dir_path)
                    cleaned_count += 1
                    total_freed_size += dir_size

                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✓ 已删除: {date_dir_name} '
                            f'(释放 {self._format_file_size(dir_size)})'
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ 删除失败 {date_dir_name}: {e}')
                )

        if cleaned_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'清理完成: 删除 {cleaned_count} 个旧备份，'
                    f'共释放 {self._format_file_size(total_freed_size)}'
                )
            )
        else:
            self.stdout.write(self.style.WARNING('  没有需要清理的旧备份'))

    def _get_dir_size(self, dir_path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
        return total_size
