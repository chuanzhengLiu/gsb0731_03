import csv
import io
import json

from django.db.models import Prefetch
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .filters import AuditLogFilter
from .models import AuditAction, AuditLog, AuditStatus, AuditTargetType
from .permissions import (
    AUDIT_VIEW_ROLES,
    AuditExportPermission,
    AuditLogPermission,
    _get_user_role,
    _get_user_store_id,
)
from .serializers import (
    AuditExportQuerySerializer,
    AuditLogDetailSerializer,
    AuditLogListSerializer,
    AuditLogQuerySerializer,
    AuditLogSerializer,
)


PLATFORM_ADMIN = 'platform_admin'


class AuditLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = AuditLog.objects.select_related('user', 'store').all()
    permission_classes = [IsAuthenticated, AuditLogPermission]
    filterset_class = AuditLogFilter
    search_fields = ['username', 'target_name', 'ip_address', 'failure_reason']
    ordering_fields = ['created_at', 'action', 'target_type', 'status']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return AuditLogListSerializer
        elif self.action == 'retrieve':
            return AuditLogDetailSerializer
        return AuditLogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = _get_user_role(user)

        if role == PLATFORM_ADMIN:
            return qs

        if role in AUDIT_VIEW_ROLES:
            user_store_id = _get_user_store_id(user)
            if user_store_id:
                return qs.filter(store_id=user_store_id)

        return qs.none()

    @action(
        detail=False,
        methods=['get'],
        url_path='stats/summary',
        permission_classes=[IsAuthenticated, AuditLogPermission],
    )
    def summary_stats(self, request):
        query_serializer = AuditLogQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        qs = self.get_queryset()

        date_from = filters.get('date_from')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = filters.get('date_to')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        if filters.get('user_id'):
            qs = qs.filter(user_id=filters['user_id'])

        if filters.get('username'):
            qs = qs.filter(username__icontains=filters['username'])

        if filters.get('store_id'):
            qs = qs.filter(store_id=filters['store_id'])

        if filters.get('action'):
            qs = qs.filter(action=filters['action'])

        if filters.get('target_type'):
            qs = qs.filter(target_type=filters['target_type'])

        if filters.get('target_id'):
            qs = qs.filter(target_id=filters['target_id'])

        if filters.get('status'):
            qs = qs.filter(status=filters['status'])

        total_count = qs.count()
        success_count = qs.filter(status=AuditStatus.SUCCESS).count()
        failed_count = qs.filter(status=AuditStatus.FAILED).count()
        pending_count = qs.filter(status=AuditStatus.PENDING).count()

        action_counts = {}
        for action_value, _ in AuditAction.choices:
            action_counts[action_value] = qs.filter(action=action_value).count()

        target_type_counts = {}
        for tt_value, _ in AuditTargetType.choices:
            target_type_counts[tt_value] = qs.filter(target_type=tt_value).count()

        user_counts = list(
            qs.values('user_id', 'username')
            .distinct()
            .order_by()
            .values_list('username', flat=True)
            .distinct()
            .count() for _ in [1]
        )[0] if total_count > 0 else 0

        data = {
            'total_count': total_count,
            'success_count': success_count,
            'failed_count': failed_count,
            'pending_count': pending_count,
            'action_counts': action_counts,
            'target_type_counts': target_type_counts,
            'unique_user_count': user_counts,
        }
        return Response(data)

    @action(
        detail=False,
        methods=['get'],
        url_path='actions/choices',
        permission_classes=[IsAuthenticated, AuditLogPermission],
    )
    def action_choices(self, request):
        choices = [
            {'value': value, 'display': display}
            for value, display in AuditAction.choices
        ]
        return Response(choices)

    @action(
        detail=False,
        methods=['get'],
        url_path='target-types/choices',
        permission_classes=[IsAuthenticated, AuditLogPermission],
    )
    def target_type_choices(self, request):
        choices = [
            {'value': value, 'display': display}
            for value, display in AuditTargetType.choices
        ]
        return Response(choices)

    @action(
        detail=False,
        methods=['get'],
        url_path='statuses/choices',
        permission_classes=[IsAuthenticated, AuditLogPermission],
    )
    def status_choices(self, request):
        choices = [
            {'value': value, 'display': display}
            for value, display in AuditStatus.choices
        ]
        return Response(choices)


class AuditExportView(APIView):
    permission_classes = [IsAuthenticated, AuditExportPermission]

    def get(self, request):
        query_serializer = AuditExportQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        user = request.user
        role = _get_user_role(user)
        user_store_id = _get_user_store_id(user)

        date_from = filters['date_from']
        date_to = filters['date_to']

        qs = AuditLog.objects.select_related('user', 'store').filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )

        if role != PLATFORM_ADMIN:
            if not user_store_id:
                return Response(
                    {'detail': _('用户未关联门店，无法导出数据')},
                    status=status.HTTP_403_FORBIDDEN,
                )
            store_id = filters.get('store_id')
            if store_id and store_id != user_store_id:
                return Response(
                    {'detail': _('无权导出其他门店数据')},
                    status=status.HTTP_403_FORBIDDEN,
                )
            qs = qs.filter(store_id=user_store_id)
        else:
            store_id = filters.get('store_id')
            if store_id:
                qs = qs.filter(store_id=store_id)

        action = filters.get('action')
        if action:
            qs = qs.filter(action=action)

        target_type = filters.get('target_type')
        if target_type:
            qs = qs.filter(target_type=target_type)

        qs = qs.order_by('created_at')

        if qs.count() > 100000:
            return Response(
                {'detail': _('导出数据量过大（超过10万条），请缩小日期范围')},
                status=status.HTTP_400_BAD_REQUEST,
            )

        headers = [
            'ID',
            '操作时间',
            '操作人ID',
            '操作人用户名',
            '操作类型',
            '目标类型',
            '目标ID',
            '目标名称',
            '门店ID',
            '门店名称',
            '变更字段',
            '额外信息',
            '操作IP',
            '浏览器UA',
            '操作状态',
            '失败原因',
        ]

        def format_value(val, max_len=1000):
            if val is None:
                return ''
            if isinstance(val, (dict, list)):
                try:
                    val_str = json.dumps(val, ensure_ascii=False)
                except (TypeError, ValueError):
                    val_str = str(val)
            else:
                val_str = str(val)
            if len(val_str) > max_len:
                val_str = val_str[:max_len] + '...'
            return val_str

        def generate_rows():
            buffer = io.StringIO()
            writer = csv.writer(buffer)

            writer.writerow(headers)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()

            batch_size = 2000
            for start in range(0, qs.count(), batch_size):
                batch = qs[start:start + batch_size]
                for log in batch:
                    details = log.details or {}
                    changes = details.get('changes', {})
                    extra = details.get('extra', {})

                    changes_summary_parts = []
                    for field, change in changes.items():
                        if isinstance(change, dict):
                            old_val = format_value(change.get('old', ''), 100)
                            new_val = format_value(change.get('new', ''), 100)
                            changes_summary_parts.append(f'{field}: {old_val} → {new_val}')
                        else:
                            changes_summary_parts.append(f'{field}: {format_value(change, 100)}')
                    changes_summary = '; '.join(changes_summary_parts)

                    row = [
                        log.id,
                        log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
                        log.user_id or '',
                        log.username or '',
                        log.get_action_display(),
                        log.get_target_type_display(),
                        log.target_id or '',
                        log.target_name or '',
                        log.store_id or '',
                        log.store.name if log.store else '',
                        changes_summary,
                        format_value(extra, 2000),
                        log.ip_address or '',
                        log.user_agent or '',
                        log.get_status_display(),
                        log.failure_reason or '',
                    ]
                    writer.writerow(row)
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()

        filename = f"audit_log_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.csv"

        response = StreamingHttpResponse(
            generate_rows(),
            content_type='text/csv; charset=utf-8',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        response.write('\ufeff')

        return response
