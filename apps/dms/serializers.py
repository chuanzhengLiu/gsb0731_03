from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.scripts.models import Script

from .models import (
    DMProfile,
    DMSkill,
    DMAvailability,
    DMTemporaryUnavailable,
)


class DMProfileListSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    name = serializers.CharField(source='user.name', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    store_id = serializers.IntegerField(source='user.store_id', read_only=True)
    store_name = serializers.SerializerMethodField()
    skill_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DMProfile
        fields = [
            'id',
            'user_id',
            'username',
            'name',
            'phone',
            'store_id',
            'store_name',
            'join_date',
            'specialty_types',
            'total_sessions',
            'avg_rating',
            'consecutive_days',
            'fatigue_warning',
            'skill_count',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'user_id',
            'username',
            'name',
            'phone',
            'store_id',
            'store_name',
            'total_sessions',
            'avg_rating',
            'consecutive_days',
            'fatigue_warning',
            'skill_count',
            'created_at',
        ]

    def get_store_name(self, obj):
        if obj.user and obj.user.store:
            return obj.user.store.name
        return None


class DMProfileDetailSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    name = serializers.CharField(source='user.name', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    store_id = serializers.IntegerField(source='user.store_id', read_only=True)
    store_name = serializers.SerializerMethodField()
    skills = serializers.SerializerMethodField()
    availabilities = serializers.SerializerMethodField()

    class Meta:
        model = DMProfile
        fields = [
            'id',
            'user_id',
            'username',
            'name',
            'phone',
            'store_id',
            'store_name',
            'join_date',
            'specialty_types',
            'total_sessions',
            'avg_rating',
            'consecutive_days',
            'fatigue_warning',
            'skills',
            'availabilities',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'user_id',
            'username',
            'name',
            'phone',
            'store_id',
            'store_name',
            'total_sessions',
            'avg_rating',
            'consecutive_days',
            'fatigue_warning',
            'skills',
            'availabilities',
            'created_at',
        ]

    def get_store_name(self, obj):
        if obj.user and obj.user.store:
            return obj.user.store.name
        return None

    def get_skills(self, obj):
        skills = obj.skills.select_related('script').all()
        return DMSkillSerializer(skills, many=True).data

    def get_availabilities(self, obj):
        availabilities = obj.availabilities.all()
        return DMAvailabilitySerializer(availabilities, many=True).data


class DMProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    name = serializers.CharField(source='user.name', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    store_id = serializers.IntegerField(source='user.store_id', read_only=True)
    store_name = serializers.SerializerMethodField()
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = DMProfile
        fields = [
            'id',
            'user',
            'user_id',
            'username',
            'name',
            'phone',
            'store_id',
            'store_name',
            'join_date',
            'specialty_types',
            'total_sessions',
            'avg_rating',
            'consecutive_days',
            'fatigue_warning',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'user_id',
            'username',
            'name',
            'phone',
            'store_id',
            'store_name',
            'total_sessions',
            'avg_rating',
            'consecutive_days',
            'fatigue_warning',
            'created_at',
        ]

    def get_store_name(self, obj):
        if obj.user and obj.user.store:
            return obj.user.store.name
        return None

    def validate_user(self, value):
        request = self.context.get('request')
        if value and request:
            current_user = request.user
            if not current_user.is_platform_admin():
                if value.store_id != current_user.store_id:
                    raise serializers.ValidationError('只能为本门店用户创建DM档案')
            if not value.is_dm():
                raise serializers.ValidationError('该用户角色不是DM')
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        if request and not self.instance:
            user = attrs.get('user')
            if not user:
                current_user = request.user
                if current_user.is_dm():
                    attrs['user'] = current_user
                else:
                    raise serializers.ValidationError({'user': '请指定用户'})
            if DMProfile.objects.filter(user=attrs['user']).exists():
                raise serializers.ValidationError({'user': '该用户已有DM档案'})
        return attrs

    def create(self, validated_data):
        return super().create(validated_data)


class DMSkillSerializer(serializers.ModelSerializer):
    dm_id = serializers.IntegerField(source='dm.id', read_only=True)
    dm_name = serializers.CharField(source='dm.user.name', read_only=True)
    script_id = serializers.IntegerField(source='script.id', read_only=True)
    script_name = serializers.CharField(source='script.name', read_only=True)
    script_type = serializers.CharField(source='script.get_type_display', read_only=True)
    script = serializers.PrimaryKeyRelatedField(
        queryset=Script.objects.all(),
        write_only=True,
        required=False,
    )
    dm = serializers.PrimaryKeyRelatedField(
        queryset=DMProfile.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = DMSkill
        fields = [
            'id',
            'dm',
            'dm_id',
            'dm_name',
            'script',
            'script_id',
            'script_name',
            'script_type',
            'proficiency',
            'play_count',
            'last_played',
        ]
        read_only_fields = [
            'id',
            'dm_id',
            'dm_name',
            'script_id',
            'script_name',
            'script_type',
            'play_count',
            'last_played',
        ]

    def validate_proficiency(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError('熟练度必须在1-5星之间')
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        if request:
            current_user = request.user
            dm = attrs.get('dm')
            if not dm and not self.instance:
                if current_user.is_dm():
                    try:
                        dm = current_user.dm_profile
                        attrs['dm'] = dm
                    except DMProfile.DoesNotExist:
                        raise serializers.ValidationError({'dm': '当前用户没有DM档案'})
                else:
                    raise serializers.ValidationError({'dm': '请指定DM档案'})

            if dm and not current_user.is_platform_admin():
                if dm.user.store_id != current_user.store_id:
                    raise serializers.ValidationError('只能为本门店DM设置技能')
                if current_user.is_dm() and dm.user_id != current_user.id:
                    raise serializers.ValidationError('只能设置自己的技能')

            script = attrs.get('script')
            if script and dm:
                qs = DMSkill.objects.filter(dm=dm, script=script)
                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError('该DM已设置过此剧本的技能')

        return attrs


class DMSetSkillSerializer(serializers.Serializer):
    script_id = serializers.IntegerField(required=True)
    proficiency = serializers.IntegerField(required=True, min_value=1, max_value=5)

    def validate_script_id(self, value):
        if not Script.objects.filter(id=value).exists():
            raise serializers.ValidationError('剧本不存在')
        return value


class DMSkillBatchUpdateSerializer(serializers.Serializer):
    skills = DMSetSkillSerializer(many=True, required=True)

    def validate_skills(self, value):
        if not value:
            raise serializers.ValidationError('技能列表不能为空')
        script_ids = [item['script_id'] for item in value]
        if len(script_ids) != len(set(script_ids)):
            raise serializers.ValidationError('技能列表中存在重复的剧本')
        return value


class DMAvailabilitySerializer(serializers.ModelSerializer):
    dm_id = serializers.IntegerField(source='dm.id', read_only=True)
    dm_name = serializers.CharField(source='dm.user.name', read_only=True)
    day_of_week_display = serializers.CharField(
        source='get_day_of_week_display',
        read_only=True,
    )
    dm = serializers.PrimaryKeyRelatedField(
        queryset=DMProfile.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = DMAvailability
        fields = [
            'id',
            'dm',
            'dm_id',
            'dm_name',
            'day_of_week',
            'day_of_week_display',
            'start_time',
            'end_time',
            'is_recurring',
            'specific_date',
            'is_unavailable',
            'note',
        ]
        read_only_fields = [
            'id',
            'dm_id',
            'dm_name',
            'day_of_week_display',
        ]

    def validate_day_of_week(self, value):
        if value < 0 or value > 6:
            raise serializers.ValidationError('星期几必须在0-6之间(周一至周日)')
        return value

    def validate(self, attrs):
        start_time = attrs.get('start_time')
        end_time = attrs.get('end_time')
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({'end_time': '结束时间必须晚于开始时间'})

        is_recurring = attrs.get('is_recurring', True)
        specific_date = attrs.get('specific_date')
        if not is_recurring and not specific_date:
            raise serializers.ValidationError({'specific_date': '非循环时必须指定日期'})

        request = self.context.get('request')
        if request:
            current_user = request.user
            dm = attrs.get('dm')
            if not dm and not self.instance:
                if current_user.is_dm():
                    try:
                        dm = current_user.dm_profile
                        attrs['dm'] = dm
                    except DMProfile.DoesNotExist:
                        raise serializers.ValidationError({'dm': '当前用户没有DM档案'})
                else:
                    raise serializers.ValidationError({'dm': '请指定DM档案'})

            if dm and not current_user.is_platform_admin():
                if dm.user.store_id != current_user.store_id:
                    raise serializers.ValidationError('只能为本门店DM设置可用时间')
                if current_user.is_dm() and dm.user_id != current_user.id:
                    raise serializers.ValidationError('只能设置自己的可用时间')

        return attrs


class _DMAvailabilityBatchItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DMAvailability
        fields = [
            'day_of_week',
            'start_time',
            'end_time',
            'is_recurring',
            'specific_date',
            'is_unavailable',
            'note',
        ]

    def validate_day_of_week(self, value):
        if value < 0 or value > 6:
            raise serializers.ValidationError('星期几必须在0-6之间(周一至周日)')
        return value


class DMAvailabilityBatchSetSerializer(serializers.Serializer):
    availabilities = _DMAvailabilityBatchItemSerializer(many=True, required=True)

    def validate_availabilities(self, value):
        if not value:
            raise serializers.ValidationError('可用时间列表不能为空')
        for item in value:
            start_time = item.get('start_time')
            end_time = item.get('end_time')
            if start_time and end_time and start_time >= end_time:
                raise serializers.ValidationError('结束时间必须晚于开始时间')
            is_recurring = item.get('is_recurring', True)
            specific_date = item.get('specific_date')
            if not is_recurring and not specific_date:
                raise serializers.ValidationError('非循环时必须指定日期')
        return value


class DMTemporaryUnavailableSerializer(serializers.ModelSerializer):
    dm_id = serializers.IntegerField(source='dm.id', read_only=True)
    dm_name = serializers.CharField(source='dm.user.name', read_only=True)
    dm = serializers.PrimaryKeyRelatedField(
        queryset=DMProfile.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = DMTemporaryUnavailable
        fields = [
            'id',
            'dm',
            'dm_id',
            'dm_name',
            'start_date',
            'end_date',
            'reason',
            'is_approved',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'dm_id',
            'dm_name',
            'is_approved',
            'created_at',
        ]

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({'end_date': '结束日期必须晚于或等于开始日期'})

        request = self.context.get('request')
        if request:
            current_user = request.user
            dm = attrs.get('dm')
            if not dm and not self.instance:
                if current_user.is_dm():
                    try:
                        dm = current_user.dm_profile
                        attrs['dm'] = dm
                    except DMProfile.DoesNotExist:
                        raise serializers.ValidationError({'dm': '当前用户没有DM档案'})
                else:
                    raise serializers.ValidationError({'dm': '请指定DM档案'})

            if dm and not current_user.is_platform_admin():
                if dm.user.store_id != current_user.store_id:
                    raise serializers.ValidationError('只能为本门店DM创建请假')
                if current_user.is_dm() and dm.user_id != current_user.id:
                    raise serializers.ValidationError('只能为自己创建请假')

        return attrs


class DMTemporaryUnavailableApproveSerializer(serializers.Serializer):
    is_approved = serializers.BooleanField(required=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class DMWorkloadStatsSerializer(serializers.Serializer):
    dm_id = serializers.IntegerField(read_only=True)
    dm_name = serializers.CharField(read_only=True)
    current_month_sessions = serializers.IntegerField(read_only=True, default=0)
    current_month_total_minutes = serializers.IntegerField(read_only=True, default=0)
    consecutive_days = serializers.IntegerField(read_only=True, default=0)
    fatigue_warning = serializers.BooleanField(read_only=True, default=False)
    fatigue_level = serializers.CharField(read_only=True)
    total_sessions = serializers.IntegerField(read_only=True, default=0)
    avg_rating = serializers.FloatField(read_only=True, default=0.0)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        consecutive = ret.get('consecutive_days', 0)
        if consecutive >= 5:
            ret['fatigue_level'] = 'critical'
        elif consecutive >= 3:
            ret['fatigue_level'] = 'warning'
        elif consecutive >= 2:
            ret['fatigue_level'] = 'normal'
        else:
            ret['fatigue_level'] = 'good'
        return ret


class DMFatigueWarningSerializer(serializers.Serializer):
    dm_id = serializers.IntegerField(read_only=True)
    dm_name = serializers.CharField(read_only=True)
    consecutive_days = serializers.IntegerField(read_only=True, default=0)
    fatigue_warning = serializers.BooleanField(read_only=True, default=False)
    fatigue_level = serializers.CharField(read_only=True)
    warning_message = serializers.CharField(read_only=True)
