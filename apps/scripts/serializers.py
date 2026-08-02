from rest_framework import serializers
from .models import Script, Role, ScriptType, ScriptDifficulty, ScriptStatus, Gender


class RoleSerializer(serializers.ModelSerializer):
    suggested_gender_display = serializers.CharField(
        source='get_suggested_gender_display',
        read_only=True
    )

    class Meta:
        model = Role
        fields = [
            'id',
            'script',
            'name',
            'suggested_gender',
            'suggested_gender_display',
            'personality_tags',
            'description',
        ]
        read_only_fields = ['id']


class RoleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            'name',
            'suggested_gender',
            'personality_tags',
            'description',
        ]


class ScriptSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_display',
        read_only=True
    )
    difficulty_display = serializers.CharField(
        source='get_difficulty_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    total_players = serializers.IntegerField(read_only=True)

    class Meta:
        model = Script
        fields = [
            'id',
            'store',
            'name',
            'type',
            'type_display',
            'player_count',
            'total_players',
            'duration_minutes',
            'difficulty',
            'difficulty_display',
            'status',
            'status_display',
            'age_tip',
            'inventory',
            'description',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ScriptCreateSerializer(serializers.ModelSerializer):
    roles = RoleCreateSerializer(many=True, required=False)

    class Meta:
        model = Script
        fields = [
            'store',
            'name',
            'type',
            'player_count',
            'duration_minutes',
            'difficulty',
            'status',
            'age_tip',
            'inventory',
            'description',
            'roles',
        ]

    def create(self, validated_data):
        roles_data = validated_data.pop('roles', [])
        script = Script.objects.create(**validated_data)
        for role_data in roles_data:
            Role.objects.create(script=script, **role_data)
        return script

    def update(self, instance, validated_data):
        roles_data = validated_data.pop('roles', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if roles_data is not None:
            instance.roles.all().delete()
            for role_data in roles_data:
                Role.objects.create(script=instance, **role_data)
        return instance


class ScriptListSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_display',
        read_only=True
    )
    difficulty_display = serializers.CharField(
        source='get_difficulty_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    total_players = serializers.IntegerField(read_only=True)

    class Meta:
        model = Script
        fields = [
            'id',
            'name',
            'type',
            'type_display',
            'player_count',
            'total_players',
            'duration_minutes',
            'difficulty',
            'difficulty_display',
            'status',
            'status_display',
            'age_tip',
            'inventory',
            'created_at',
        ]


class ScriptDetailSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(
        source='get_type_display',
        read_only=True
    )
    difficulty_display = serializers.CharField(
        source='get_difficulty_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    total_players = serializers.IntegerField(read_only=True)
    roles = RoleSerializer(many=True, read_only=True)

    class Meta:
        model = Script
        fields = [
            'id',
            'store',
            'name',
            'type',
            'type_display',
            'player_count',
            'total_players',
            'duration_minutes',
            'difficulty',
            'difficulty_display',
            'status',
            'status_display',
            'age_tip',
            'inventory',
            'description',
            'created_at',
            'roles',
        ]
        read_only_fields = ['id', 'created_at']


class ScriptRecommendationQuerySerializer(serializers.Serializer):
    player_count = serializers.IntegerField(
        required=True,
        min_value=1,
        help_text='玩家人数'
    )
    preferred_types = serializers.MultipleChoiceField(
        choices=ScriptType.choices,
        required=False,
        help_text='偏好的剧本类型（可多选）'
    )
