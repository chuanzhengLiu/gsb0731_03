from django.db import models as django_models
from django.utils import timezone
from rest_framework import serializers

from .models import Schedule, ScheduleConflict, ScheduleStatus, ConflictType


class ScheduleSerializer(serializers.ModelSerializer):
    dm_name = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    script_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    scheduled_start = serializers.SerializerMethodField()
    scheduled_end = serializers.SerializerMethodField()
    player_count = serializers.IntegerField(read_only=True)
    store_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Schedule
        fields = [
            'id', 'booking', 'dm', 'dm_name', 'room', 'room_name',
            'script', 'script_name', 'status', 'status_display',
            'actual_start_time', 'actual_end_time', 'is_locked',
            'scheduled_start', 'scheduled_end', 'player_count',
            'store_id', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_dm_name(self, obj):
        if obj.dm_id:
            try:
                from django.apps import apps
                DMProfile = apps.get_model('accounts', 'DMProfile')
                dm = DMProfile.objects.filter(pk=obj.dm_id).first()
                if dm:
                    user = getattr(dm, 'user', None)
                    if user:
                        return getattr(user, 'name', '') or getattr(user, 'username', '')
                    return str(dm)
            except LookupError:
                pass
        return ''

    def get_room_name(self, obj):
        if obj.room_id:
            try:
                from django.apps import apps
                Room = apps.get_model('stores', 'Room')
                room = Room.objects.filter(pk=obj.room_id).first()
                return str(room) if room else ''
            except LookupError:
                pass
        return ''

    def get_script_name(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.name if script else ''
            except LookupError:
                pass
        return ''

    def get_scheduled_start(self, obj):
        return obj.scheduled_start_time

    def get_scheduled_end(self, obj):
        return obj.scheduled_end_time

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.is_locked:
            if any(k in attrs for k in ['dm', 'room', 'script']):
                raise serializers.ValidationError('已锁定的排班不能修改分配信息')
        return attrs


class ScheduleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = [
            'id', 'booking', 'dm', 'room', 'script', 'status',
            'actual_start_time', 'actual_end_time', 'is_locked',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_booking(self, value):
        if Schedule.objects.filter(booking=value).exists():
            raise serializers.ValidationError('该预约已有排班记录')
        return value

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._check_and_create_conflicts(instance)
        return instance

    def _check_and_create_conflicts(self, schedule):
        from .utils import detect_conflicts_for_schedule
        detect_conflicts_for_schedule(schedule)


class ScheduleListSerializer(serializers.ModelSerializer):
    dm_name = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    script_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    scheduled_start = serializers.SerializerMethodField()
    player_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Schedule
        fields = [
            'id', 'booking', 'dm_name', 'room_name', 'script_name',
            'status', 'status_display', 'is_locked', 'scheduled_start',
            'player_count', 'created_at',
        ]

    def get_dm_name(self, obj):
        if obj.dm_id:
            try:
                from django.apps import apps
                DMProfile = apps.get_model('accounts', 'DMProfile')
                dm = DMProfile.objects.filter(pk=obj.dm_id).first()
                if dm:
                    user = getattr(dm, 'user', None)
                    if user:
                        return getattr(user, 'name', '') or getattr(user, 'username', '')
            except LookupError:
                pass
        return ''

    def get_room_name(self, obj):
        if obj.room_id:
            try:
                from django.apps import apps
                Room = apps.get_model('stores', 'Room')
                room = Room.objects.filter(pk=obj.room_id).first()
                return room.name if room else ''
            except LookupError:
                pass
        return ''

    def get_script_name(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.name if script else ''
            except LookupError:
                pass
        return ''

    def get_scheduled_start(self, obj):
        return obj.scheduled_start_time


class ScheduleDetailSerializer(serializers.ModelSerializer):
    dm_name = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    room_capacity = serializers.SerializerMethodField()
    script_name = serializers.SerializerMethodField()
    script_type = serializers.SerializerMethodField()
    script_duration = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    scheduled_start = serializers.SerializerMethodField()
    scheduled_end = serializers.SerializerMethodField()
    player_count = serializers.IntegerField(read_only=True)
    booking_info = serializers.SerializerMethodField()
    conflict_count = serializers.SerializerMethodField()
    can_modify = serializers.BooleanField(read_only=True)

    class Meta:
        model = Schedule
        fields = [
            'id', 'booking', 'booking_info', 'dm', 'dm_name',
            'room', 'room_name', 'room_capacity',
            'script', 'script_name', 'script_type', 'script_duration',
            'status', 'status_display', 'actual_start_time', 'actual_end_time',
            'is_locked', 'can_modify', 'scheduled_start', 'scheduled_end',
            'player_count', 'conflict_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_dm_name(self, obj):
        if obj.dm_id:
            try:
                from django.apps import apps
                DMProfile = apps.get_model('accounts', 'DMProfile')
                dm = DMProfile.objects.filter(pk=obj.dm_id).first()
                if dm:
                    user = getattr(dm, 'user', None)
                    if user:
                        return getattr(user, 'name', '') or getattr(user, 'username', '')
                    return str(dm)
            except LookupError:
                pass
        return ''

    def get_room_name(self, obj):
        if obj.room_id:
            try:
                from django.apps import apps
                Room = apps.get_model('stores', 'Room')
                room = Room.objects.filter(pk=obj.room_id).first()
                return str(room) if room else ''
            except LookupError:
                pass
        return ''

    def get_room_capacity(self, obj):
        if obj.room_id:
            try:
                from django.apps import apps
                Room = apps.get_model('stores', 'Room')
                room = Room.objects.filter(pk=obj.room_id).first()
                return room.capacity if room else 0
            except LookupError:
                pass
        return 0

    def get_script_name(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.name if script else ''
            except LookupError:
                pass
        return ''

    def get_script_type(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.get_type_display() if script else ''
            except LookupError:
                pass
        return ''

    def get_script_duration(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.duration_minutes if script else 0
            except LookupError:
                pass
        return 0

    def get_scheduled_start(self, obj):
        return obj.scheduled_start_time

    def get_scheduled_end(self, obj):
        return obj.scheduled_end_time

    def get_booking_info(self, obj):
        if obj.booking_id:
            try:
                from django.apps import apps
                Booking = apps.get_model('bookings', 'Booking')
                booking = Booking.objects.filter(pk=obj.booking_id).first()
                if booking:
                    return {
                        'id': booking.id,
                        'player_count': getattr(booking, 'player_count', 0),
                        'contact_name': getattr(booking, 'contact_name', ''),
                        'contact_phone': getattr(booking, 'contact_phone', ''),
                        'notes': getattr(booking, 'notes', ''),
                    }
            except LookupError:
                pass
        return None

    def get_conflict_count(self, obj):
        return ScheduleConflict.objects.filter(
            django_models.Q(schedule1=obj) | django_models.Q(schedule2=obj),
            resolved=False
        ).count()

    def get_can_modify(self, obj):
        return obj.can_modify(by_algorithm=False)


class ScheduleStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = ['id', 'status', 'actual_start_time', 'actual_end_time']
        read_only_fields = ['id']

    def validate_status(self, value):
        instance = self.instance
        if not instance:
            return value

        current = instance.status
        valid_transitions = {
            ScheduleStatus.ASSIGNED: [
                ScheduleStatus.DM_CONFIRMED,
                ScheduleStatus.CANCELLED,
            ],
            ScheduleStatus.DM_CONFIRMED: [
                ScheduleStatus.IN_PROGRESS,
                ScheduleStatus.CANCELLED,
                ScheduleStatus.ASSIGNED,
            ],
            ScheduleStatus.IN_PROGRESS: [
                ScheduleStatus.COMPLETED,
                ScheduleStatus.CANCELLED,
            ],
            ScheduleStatus.COMPLETED: [],
            ScheduleStatus.CANCELLED: [],
        }

        if value not in valid_transitions.get(current, []):
            try:
                target_display = dict(ScheduleStatus.choices).get(value, value)
            except Exception:
                target_display = value
            raise serializers.ValidationError(
                f'不能从 {instance.get_status_display()} 状态转换到 {target_display}'
            )
        return value

    def validate(self, attrs):
        status = attrs.get('status')
        if status == ScheduleStatus.IN_PROGRESS and 'actual_start_time' not in attrs:
            attrs['actual_start_time'] = timezone.now()
        if status == ScheduleStatus.COMPLETED and 'actual_end_time' not in attrs:
            attrs['actual_end_time'] = timezone.now()
        return attrs


class SchedulingRequestSerializer(serializers.Serializer):
    start_date = serializers.DateField(required=True, label='开始日期')
    end_date = serializers.DateField(required=True, label='结束日期')
    store_id = serializers.IntegerField(required=True, label='门店ID')
    force_regenerate = serializers.BooleanField(
        required=False,
        default=False,
        label='是否强制重新生成（忽略已确认的排班）',
    )

    def validate(self, attrs):
        if attrs['start_date'] > attrs['end_date']:
            raise serializers.ValidationError('开始日期不能晚于结束日期')
        date_range = (attrs['end_date'] - attrs['start_date']).days
        if date_range > 31:
            raise serializers.ValidationError('排班日期范围不能超过31天')
        return attrs


class ScheduleAssignmentSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    dm_id = serializers.IntegerField()
    room_id = serializers.IntegerField()
    script_id = serializers.IntegerField()
    match_score = serializers.FloatField()
    is_new = serializers.BooleanField()


class ConflictReportSerializer(serializers.Serializer):
    conflict_type = serializers.CharField()
    description = serializers.CharField()
    booking_id = serializers.IntegerField(allow_null=True)
    dm_id = serializers.IntegerField(allow_null=True)
    room_id = serializers.IntegerField(allow_null=True)
    severity = serializers.CharField()


class SchedulingResultSerializer(serializers.Serializer):
    assignments = ScheduleAssignmentSerializer(many=True)
    unassigned_bookings = serializers.ListField(child=serializers.IntegerField())
    conflicts = ConflictReportSerializer(many=True)
    total_score = serializers.FloatField()
    solver_status = serializers.CharField()
    solve_time_seconds = serializers.FloatField()


class ConflictSerializer(serializers.ModelSerializer):
    conflict_type_display = serializers.CharField(
        source='get_conflict_type_display',
        read_only=True,
    )
    schedule1_info = serializers.SerializerMethodField()
    schedule2_info = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleConflict
        fields = [
            'id', 'schedule1', 'schedule1_info', 'schedule2', 'schedule2_info',
            'conflict_type', 'conflict_type_display', 'description',
            'resolved', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_schedule1_info(self, obj):
        return self._get_schedule_info(obj.schedule1)

    def get_schedule2_info(self, obj):
        return self._get_schedule_info(obj.schedule2)

    def _get_schedule_info(self, schedule):
        if not schedule:
            return None
        return {
            'id': schedule.id,
            'booking_id': schedule.booking_id,
            'dm_id': schedule.dm_id,
            'room_id': schedule.room_id,
            'status': schedule.status,
            'status_display': schedule.get_status_display(),
            'scheduled_start': schedule.scheduled_start_time,
        }


class ReassignmentRequestSerializer(serializers.Serializer):
    dm_id = serializers.IntegerField(required=True, label='请假DM的ID')
    start_date = serializers.DateField(required=True, label='请假开始日期')
    end_date = serializers.DateField(required=True, label='请假结束日期')
    store_id = serializers.IntegerField(required=True, label='门店ID')
    reason = serializers.CharField(
        required=False,
        max_length=500,
        allow_blank=True,
        label='请假原因',
    )

    def validate(self, attrs):
        if attrs['start_date'] > attrs['end_date']:
            raise serializers.ValidationError('开始日期不能晚于结束日期')
        return attrs


class ScheduleCalendarItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    resourceId = serializers.CharField()
    color = serializers.CharField()
    extendedProps = serializers.DictField()
