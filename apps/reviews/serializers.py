from rest_framework import serializers

from .models import Review, ScriptStats


class PlayerPerformanceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
    )


class DMReviewDataSerializer(serializers.Serializer):
    player_performance = PlayerPerformanceSerializer(
        many=True,
        required=False,
        default=list,
    )
    has_quit = serializers.BooleanField(required=False, default=False)
    has_idle = serializers.BooleanField(required=False, default=False)
    script_bugs = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
    )
    improvement = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
    )
    special_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
    )


class ReviewSerializer(serializers.ModelSerializer):
    schedule_info = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    has_player_review = serializers.BooleanField(read_only=True)
    has_dm_review = serializers.BooleanField(read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'schedule', 'schedule_info',
            'dm_rating', 'script_rating',
            'dm_tags', 'script_tags', 'comment',
            'dm_review',
            'completed_by', 'completed_by_name',
            'has_player_review', 'has_dm_review',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_schedule_info(self, obj):
        schedule = obj.schedule
        if not schedule:
            return None
        info = {
            'id': schedule.id,
            'booking_id': schedule.booking_id,
            'status': schedule.status,
            'status_display': schedule.get_status_display(),
            'script_id': schedule.script_id,
            'dm_id': schedule.dm_id,
            'room_id': schedule.room_id,
        }
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script = Script.objects.filter(pk=schedule.script_id).first()
            if script:
                info['script_name'] = script.name
                info['script_type'] = script.get_type_display()
        except LookupError:
            pass
        try:
            from django.apps import apps
            DMProfile = apps.get_model('accounts', 'DMProfile')
            dm = DMProfile.objects.filter(pk=schedule.dm_id).select_related('user').first()
            if dm and dm.user:
                name = getattr(dm.user, 'name', '') or getattr(dm.user, 'username', '')
                info['dm_name'] = name
        except LookupError:
            pass
        return info

    def get_completed_by_name(self, obj):
        if obj.completed_by_id:
            user = obj.completed_by
            return getattr(user, 'name', '') or getattr(user, 'username', '')
        return ''


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = [
            'id', 'schedule',
            'dm_rating', 'script_rating',
            'dm_tags', 'script_tags', 'comment',
            'dm_review',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_schedule(self, value):
        if Review.objects.filter(schedule=value).exists():
            raise serializers.ValidationError('该排班已有评价记录')
        return value


class ReviewDetailSerializer(serializers.ModelSerializer):
    schedule_detail = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    store_id = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            'id', 'schedule', 'schedule_detail',
            'dm_rating', 'script_rating',
            'dm_tags', 'script_tags', 'comment',
            'dm_review',
            'completed_by', 'completed_by_name',
            'store_id',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_schedule_detail(self, obj):
        schedule = obj.schedule
        if not schedule:
            return None
        result = {
            'id': schedule.id,
            'booking_id': schedule.booking_id,
            'status': schedule.status,
            'status_display': schedule.get_status_display(),
            'actual_start_time': schedule.actual_start_time,
            'actual_end_time': schedule.actual_end_time,
            'scheduled_start': schedule.scheduled_start_time,
            'scheduled_end': schedule.scheduled_end_time,
            'player_count': schedule.player_count,
        }
        try:
            from django.apps import apps
            Script = apps.get_model('scripts', 'Script')
            script = Script.objects.filter(pk=schedule.script_id).first()
            if script:
                result['script_id'] = script.id
                result['script_name'] = script.name
                result['script_type'] = script.get_type_display()
                result['script_duration'] = script.duration_minutes
        except LookupError:
            pass
        try:
            from django.apps import apps
            DMProfile = apps.get_model('accounts', 'DMProfile')
            dm = DMProfile.objects.filter(pk=schedule.dm_id).select_related('user').first()
            if dm and dm.user:
                result['dm_id'] = dm.id
                result['dm_user_id'] = dm.user_id
                name = getattr(dm.user, 'name', '') or getattr(dm.user, 'username', '')
                result['dm_name'] = name
        except LookupError:
            pass
        try:
            from django.apps import apps
            Room = apps.get_model('stores', 'Room')
            room = Room.objects.filter(pk=schedule.room_id).first()
            if room:
                result['room_id'] = room.id
                result['room_name'] = room.name
                result['store_id'] = room.store_id
        except LookupError:
            pass
        return result

    def get_completed_by_name(self, obj):
        if obj.completed_by_id:
            user = obj.completed_by
            return getattr(user, 'name', '') or getattr(user, 'username', '')
        return ''

    def get_store_id(self, obj):
        return obj.store_id


class PlayerReviewSerializer(serializers.ModelSerializer):
    dm_rating = serializers.IntegerField(
        required=True,
        min_value=1,
        max_value=5,
    )
    script_rating = serializers.IntegerField(
        required=True,
        min_value=1,
        max_value=5,
    )
    dm_tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
    )
    script_tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default='',
    )

    class Meta:
        model = Review
        fields = [
            'id', 'schedule',
            'dm_rating', 'script_rating',
            'dm_tags', 'script_tags', 'comment',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        schedule = attrs.get('schedule') or getattr(self.instance, 'schedule', None)
        if not schedule:
            raise serializers.ValidationError({'schedule': '必须指定排班'})
        phone = self.context.get('request').data.get('phone') if self.context.get('request') else None
        if not phone:
            raise serializers.ValidationError({'phone': '必须提供手机号进行验证'})
        try:
            from django.apps import apps
            Booking = apps.get_model('bookings', 'Booking')
            booking = Booking.objects.filter(pk=schedule.booking_id).first()
            if not booking:
                raise serializers.ValidationError({'schedule': '排班未关联预约'})
            booking_players = list(booking.players.all().values_list('phone', flat=True))
            customer_phone = getattr(booking, 'customer_phone', None)
            valid_phones = [p for p in booking_players if p]
            if customer_phone:
                valid_phones.append(customer_phone)
            if phone not in valid_phones:
                raise serializers.ValidationError({'phone': '手机号与预约信息不匹配'})
        except LookupError:
            pass
        return attrs


class DMReviewSerializer(serializers.ModelSerializer):
    dm_review = DMReviewDataSerializer(required=True)

    class Meta:
        model = Review
        fields = [
            'id', 'schedule',
            'dm_review',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        schedule = attrs.get('schedule') or getattr(self.instance, 'schedule', None)
        if not schedule:
            raise serializers.ValidationError({'schedule': '必须指定排班'})
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            try:
                from django.apps import apps
                DMProfile = apps.get_model('accounts', 'DMProfile')
                dm_profile = DMProfile.objects.filter(user_id=request.user.id).first()
                if dm_profile and schedule.dm_id != dm_profile.id:
                    raise serializers.ValidationError({'schedule': '只能填写自己带本场次的复盘'})
            except LookupError:
                pass
        return attrs


class ScriptStatsSerializer(serializers.ModelSerializer):
    overall_rating = serializers.FloatField(read_only=True)

    class Meta:
        model = ScriptStats
        fields = [
            'id', 'script',
            'avg_dm_rating', 'avg_script_rating', 'overall_rating',
            'total_sessions', 'completed_sessions', 'completion_rate',
            'complaint_count', 'turnover_rate',
            'last_updated',
        ]
        read_only_fields = ['id', 'last_updated', 'overall_rating']


class ScriptStatsListSerializer(serializers.ModelSerializer):
    script_name = serializers.SerializerMethodField()
    script_type = serializers.SerializerMethodField()
    script_type_display = serializers.SerializerMethodField()
    store_id = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    overall_rating = serializers.FloatField(read_only=True)

    class Meta:
        model = ScriptStats
        fields = [
            'id', 'script', 'script_name', 'script_type', 'script_type_display',
            'store_id', 'store_name',
            'avg_dm_rating', 'avg_script_rating', 'overall_rating',
            'total_sessions', 'completed_sessions', 'completion_rate',
            'complaint_count', 'turnover_rate',
            'last_updated',
        ]
        read_only_fields = ['id', 'last_updated', 'overall_rating']

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
                return script.type if script else ''
            except LookupError:
                pass
        return ''

    def get_script_type_display(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.get_type_display() if script else ''
            except LookupError:
                pass
        return ''

    def get_store_id(self, obj):
        if obj.script_id:
            try:
                from django.apps import apps
                Script = apps.get_model('scripts', 'Script')
                script = Script.objects.filter(pk=obj.script_id).first()
                return script.store_id if script else None
            except LookupError:
                pass
        return None

    def get_store_name(self, obj):
        store_id = self.get_store_id(obj)
        if store_id:
            try:
                from django.apps import apps
                Store = apps.get_model('stores', 'Store')
                store = Store.objects.filter(pk=store_id).first()
                return store.name if store else ''
            except LookupError:
                pass
        return ''
