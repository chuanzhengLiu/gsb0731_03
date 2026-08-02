from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import (
    AuditAction,
    AuditLog,
    AuditStatus,
    AuditTargetType,
)


class AuditLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(
        source='get_action_display',
        read_only=True,
    )
    target_type_display = serializers.CharField(
        source='get_target_type_display',
        read_only=True,
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True,
        default=None,
    )

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'user',
            'username',
            'action',
            'action_display',
            'target_type',
            'target_type_display',
            'target_id',
            'target_name',
            'store',
            'store_name',
            'details',
            'ip_address',
            'user_agent',
            'status',
            'status_display',
            'failure_reason',
            'created_at',
        ]
        read_only_fields = fields


class AuditLogListSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(
        source='get_action_display',
        read_only=True,
    )
    target_type_display = serializers.CharField(
        source='get_target_type_display',
        read_only=True,
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True,
        default=None,
    )

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'username',
            'action',
            'action_display',
            'target_type',
            'target_type_display',
            'target_id',
            'target_name',
            'store_name',
            'ip_address',
            'status',
            'status_display',
            'failure_reason',
            'created_at',
        ]
        read_only_fields = fields


class AuditLogDetailSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(
        source='get_action_display',
        read_only=True,
    )
    target_type_display = serializers.CharField(
        source='get_target_type_display',
        read_only=True,
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True,
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True,
        default=None,
    )
    changes_summary = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'user',
            'username',
            'action',
            'action_display',
            'target_type',
            'target_type_display',
            'target_id',
            'target_name',
            'store',
            'store_name',
            'details',
            'changes_summary',
            'ip_address',
            'user_agent',
            'status',
            'status_display',
            'failure_reason',
            'created_at',
        ]
        read_only_fields = fields

    def get_changes_summary(self, obj):
        details = obj.details or {}
        changes = details.get('changes', {})
        if not changes:
            return None
        summary = []
        for field, change in changes.items():
            if isinstance(change, dict):
                old = change.get('old', '')
                new = change.get('new', '')
                summary.append({
                    'field': field,
                    'old': str(old)[:100] if old is not None else '',
                    'new': str(new)[:100] if new is not None else '',
                })
        return summary


class AuditLogQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(
        required=False,
        help_text=_('开始日期 (YYYY-MM-DD)'),
    )
    date_to = serializers.DateField(
        required=False,
        help_text=_('结束日期 (YYYY-MM-DD)'),
    )
    user_id = serializers.IntegerField(
        required=False,
        help_text=_('操作人用户ID'),
    )
    username = serializers.CharField(
        required=False,
        max_length=150,
        help_text=_('用户名（模糊匹配）'),
    )
    store_id = serializers.IntegerField(
        required=False,
        help_text=_('门店ID'),
    )
    action = serializers.ChoiceField(
        choices=AuditAction.choices,
        required=False,
        help_text=_('操作类型'),
    )
    target_type = serializers.ChoiceField(
        choices=AuditTargetType.choices,
        required=False,
        help_text=_('目标类型'),
    )
    target_id = serializers.IntegerField(
        required=False,
        help_text=_('目标ID'),
    )
    status = serializers.ChoiceField(
        choices=AuditStatus.choices,
        required=False,
        help_text=_('操作状态'),
    )
    ip_address = serializers.CharField(
        required=False,
        max_length=45,
        help_text=_('操作IP（模糊匹配）'),
    )


class AuditExportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(
        required=True,
        help_text=_('开始日期 (YYYY-MM-DD)'),
    )
    date_to = serializers.DateField(
        required=True,
        help_text=_('结束日期 (YYYY-MM-DD)'),
    )
    store_id = serializers.IntegerField(
        required=False,
        help_text=_('门店ID（可选，不填则导出所有有权限门店）'),
    )
    action = serializers.ChoiceField(
        choices=AuditAction.choices,
        required=False,
        help_text=_('操作类型（可选）'),
    )
    target_type = serializers.ChoiceField(
        choices=AuditTargetType.choices,
        required=False,
        help_text=_('目标类型（可选）'),
    )

    def validate(self, attrs):
        date_from = attrs.get('date_from')
        date_to = attrs.get('date_to')
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(_('开始日期不能晚于结束日期'))
        return attrs
