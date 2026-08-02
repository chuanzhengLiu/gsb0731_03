from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
from rest_framework import serializers

from .models import (
    Booking,
    BookingPlayer,
    BookingStatus,
    PlayerGender,
    validate_status_transition,
)
from apps.scripts.models import Script, ScriptStatus, ScriptType
from apps.scripts.serializers import ScriptListSerializer


class BookingPlayerSerializer(serializers.ModelSerializer):
    gender_display = serializers.CharField(
        source='get_gender_display',
        read_only=True
    )

    class Meta:
        model = BookingPlayer
        fields = [
            'id',
            'booking',
            'name',
            'phone',
            'gender',
            'gender_display',
            'tags',
            'horror_tolerance',
            'accept_reverse',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class BookingPlayerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingPlayer
        fields = [
            'name',
            'phone',
            'gender',
            'tags',
            'horror_tolerance',
            'accept_reverse',
        ]

    def validate_horror_tolerance(self, value):
        if value is not None and (value < 0 or value > 3):
            raise serializers.ValidationError('恐怖耐受度必须在0-3之间')
        return value


class BookingPlayerBulkCreateSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField(required=True)
    players = BookingPlayerCreateSerializer(many=True, required=True)

    def validate_booking_id(self, value):
        if not Booking.objects.filter(id=value).exists():
            raise serializers.ValidationError('预约不存在')
        return value

    def create(self, validated_data):
        booking_id = validated_data['booking_id']
        players_data = validated_data['players']
        players = []
        for player_data in players_data:
            player = BookingPlayer.objects.create(
                booking_id=booking_id,
                **player_data
            )
            players.append(player)
        return players


class BookingSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True
    )
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )
    end_time = serializers.TimeField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id',
            'store',
            'store_name',
            'date',
            'start_time',
            'end_time',
            'duration_minutes',
            'player_count',
            'preferences',
            'status',
            'status_display',
            'customer_name',
            'customer_phone',
            'deposit_amount',
            'created_by',
            'created_by_name',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class BookingCreateSerializer(serializers.ModelSerializer):
    players = BookingPlayerCreateSerializer(many=True, required=False)

    class Meta:
        model = Booking
        fields = [
            'store',
            'date',
            'start_time',
            'duration_minutes',
            'player_count',
            'preferences',
            'customer_name',
            'customer_phone',
            'deposit_amount',
            'players',
        ]

    def validate_player_count(self, value):
        if value <= 0:
            raise serializers.ValidationError('玩家人数必须大于0')
        return value

    def validate_duration_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError('时长必须大于0')
        return value

    def validate_deposit_amount(self, value):
        if value < 0:
            raise serializers.ValidationError('订金金额不能为负数')
        return value

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('偏好设置必须是字典格式')

        preferred_types = value.get('preferred_types', [])
        if preferred_types and not isinstance(preferred_types, list):
            raise serializers.ValidationError('preferred_types 必须是数组')

        valid_types = dict(ScriptType.choices).keys()
        for ptype in preferred_types:
            if ptype not in valid_types:
                raise serializers.ValidationError(f'无效的剧本类型: {ptype}')

        difficulty = value.get('difficulty_preference')
        if difficulty is not None:
            if not isinstance(difficulty, int) or difficulty < 1 or difficulty > 4:
                raise serializers.ValidationError('difficulty_preference 必须是1-4的整数')

        is_newbie = value.get('is_newbie')
        if is_newbie is not None and not isinstance(is_newbie, bool):
            raise serializers.ValidationError('is_newbie 必须是布尔值')

        player_notes = value.get('player_notes')
        if player_notes is not None and not isinstance(player_notes, str):
            raise serializers.ValidationError('player_notes 必须是字符串')

        return value

    def validate(self, attrs):
        store = attrs.get('store') or (self.instance.store if self.instance else None)
        date = attrs.get('date') or (self.instance.date if self.instance else None)
        start_time = attrs.get('start_time') or (self.instance.start_time if self.instance else None)
        duration_minutes = attrs.get('duration_minutes')
        if duration_minutes is None and self.instance:
            duration_minutes = self.instance.duration_minutes
        if duration_minutes is None:
            duration_minutes = 240

        if store and date and start_time:
            start_dt = datetime.combine(date, start_time)
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            conflicting_bookings = Booking.objects.filter(
                store=store,
                date=date,
                status__in=[BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS]
            )

            for booking in conflicting_bookings:
                if self.instance and booking.id == self.instance.id:
                    continue
                booking_start = datetime.combine(booking.date, booking.start_time)
                booking_end = booking_start + timedelta(minutes=booking.duration_minutes)
                if start_dt < booking_end and booking_start < end_dt:
                    raise serializers.ValidationError(
                        f'该时段与已确认预约 #{booking.id} 冲突 '
                        f'({booking.start_time} - {booking.end_time()})'
                    )

            if self.instance:
                try:
                    from apps.scheduling.models import Schedule
                    from apps.scheduling.utils import (
                        get_dm_unavailabilities,
                        MIN_SCHEDULE_GAP_MINUTES,
                    )

                    schedule = Schedule.objects.filter(booking=self.instance).first()
                    if schedule and schedule.dm_id:
                        store_id = store.id if hasattr(store, 'id') else store
                        unavailabilities = get_dm_unavailabilities(
                            start=start_dt,
                            end=end_dt,
                            store_id=store_id,
                            exclude_schedule_id=schedule.id,
                        )
                        if schedule.dm_id in unavailabilities:
                            info = unavailabilities[schedule.dm_id]
                            if info['gap_minutes'] == 0:
                                raise serializers.ValidationError(
                                    f'新时段与DM的其他排班时间冲突（排班#{info["schedule_id"]}）'
                                )
                            raise serializers.ValidationError(
                                f'新时段与DM的其他排班间隔仅{info["gap_minutes"]}分钟，'
                                f'不足{MIN_SCHEDULE_GAP_MINUTES}分钟（相邻排班#{info["schedule_id"]}）'
                            )
                except ImportError:
                    pass

        return attrs

    def create(self, validated_data):
        players_data = validated_data.pop('players', [])
        user = self.context['request'].user
        validated_data['status'] = BookingStatus.PENDING
        validated_data['created_by'] = user
        booking = Booking.objects.create(**validated_data)

        for player_data in players_data:
            BookingPlayer.objects.create(booking=booking, **player_data)

        return booking


class BookingListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True
    )
    player_count_actual = serializers.IntegerField(
        source='players.count',
        read_only=True
    )

    class Meta:
        model = Booking
        fields = [
            'id',
            'store_name',
            'date',
            'start_time',
            'duration_minutes',
            'player_count',
            'player_count_actual',
            'status',
            'status_display',
            'customer_name',
            'customer_phone',
            'deposit_amount',
            'created_at',
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    store_name = serializers.CharField(
        source='store.name',
        read_only=True
    )
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True
    )
    end_time = serializers.TimeField(read_only=True)
    players = BookingPlayerSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id',
            'store',
            'store_name',
            'date',
            'start_time',
            'end_time',
            'duration_minutes',
            'player_count',
            'preferences',
            'status',
            'status_display',
            'customer_name',
            'customer_phone',
            'deposit_amount',
            'created_by',
            'created_by_name',
            'created_at',
            'updated_at',
            'players',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class BookingStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BookingStatus.choices)

    def validate_status(self, value):
        instance = self.context.get('instance')
        if instance:
            try:
                validate_status_transition(instance.status, value)
            except ValidationError as e:
                raise serializers.ValidationError(str(e))
        return value


class ScriptRecommendationQuerySerializer(serializers.Serializer):
    store_id = serializers.IntegerField(required=True, help_text='门店ID')
    player_count = serializers.IntegerField(required=True, min_value=1, help_text='玩家人数')
    preferred_types = serializers.MultipleChoiceField(
        choices=ScriptType.choices,
        required=False,
        help_text='偏好的剧本类型（可多选）'
    )
    difficulty_preference = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=4,
        help_text='难度偏好（1-4）'
    )
    is_newbie = serializers.BooleanField(required=False, help_text='是否新手')


class BookingWithScriptRecommendationSerializer(serializers.Serializer):
    booking_data = BookingCreateSerializer()
    recommendation_query = ScriptRecommendationQuerySerializer(required=False)

    def validate(self, attrs):
        recommendation_query = attrs.get('recommendation_query')
        booking_data = attrs.get('booking_data', {})

        if recommendation_query:
            if 'store_id' not in recommendation_query:
                recommendation_query['store_id'] = booking_data.get('store').id \
                    if booking_data.get('store') else None
            if 'player_count' not in recommendation_query:
                recommendation_query['player_count'] = booking_data.get('player_count')

            preferences = booking_data.get('preferences', {})
            if 'preferred_types' not in recommendation_query:
                preferred_types = preferences.get('preferred_types', [])
                if preferred_types:
                    recommendation_query['preferred_types'] = preferred_types
            if 'difficulty_preference' not in recommendation_query:
                difficulty = preferences.get('difficulty_preference')
                if difficulty is not None:
                    recommendation_query['difficulty_preference'] = difficulty
            if 'is_newbie' not in recommendation_query:
                is_newbie = preferences.get('is_newbie')
                if is_newbie is not None:
                    recommendation_query['is_newbie'] = is_newbie

        return attrs
