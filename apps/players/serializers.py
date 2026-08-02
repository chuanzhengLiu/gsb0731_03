from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.scripts.models import Role, ScriptType
from apps.scheduling.models import Schedule

from .models import (
    PlayerProfile,
    RoleAssignment,
    PREFERENCE_TAGS,
    validate_preference_tags,
    validate_horror_tolerance,
)
from .algorithms.matcher import (
    MatchPlayer,
    MatchRole,
    run_role_matching,
    MatchResult,
)


class PlayerPreferenceTagSerializer(serializers.Serializer):
    tag = serializers.ChoiceField(choices=PREFERENCE_TAGS)


class PlayerProfileSerializer(serializers.ModelSerializer):
    total_plays = serializers.IntegerField(read_only=True)
    last_visit_date = serializers.DateField(read_only=True, allow_null=True)
    avg_satisfaction = serializers.FloatField(read_only=True, allow_null=True)

    class Meta:
        model = PlayerProfile
        fields = [
            'id',
            'phone',
            'name',
            'preference_tags',
            'horror_tolerance',
            'accept_reverse',
            'history_roles',
            'total_plays',
            'last_visit_date',
            'avg_satisfaction',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_preference_tags(self, value):
        validate_preference_tags(value)
        return value

    def validate_horror_tolerance(self, value):
        validate_horror_tolerance(value)
        return value

    def validate(self, attrs):
        phone = attrs.get('phone')
        name = attrs.get('name')
        if not phone and not name:
            raise serializers.ValidationError({
                'phone': '匿名玩家必须填写姓名',
                'name': '匿名玩家必须填写姓名',
            })
        return attrs


class PlayerProfileListSerializer(serializers.ModelSerializer):
    total_plays = serializers.IntegerField(read_only=True)
    last_visit_date = serializers.DateField(read_only=True, allow_null=True)

    class Meta:
        model = PlayerProfile
        fields = [
            'id',
            'phone',
            'name',
            'preference_tags',
            'horror_tolerance',
            'accept_reverse',
            'total_plays',
            'last_visit_date',
            'created_at',
        ]


class PlayerProfileDetailSerializer(serializers.ModelSerializer):
    total_plays = serializers.IntegerField(read_only=True)
    last_visit_date = serializers.DateField(read_only=True, allow_null=True)
    avg_satisfaction = serializers.FloatField(read_only=True, allow_null=True)

    class Meta:
        model = PlayerProfile
        fields = [
            'id',
            'phone',
            'name',
            'preference_tags',
            'horror_tolerance',
            'accept_reverse',
            'history_roles',
            'total_plays',
            'last_visit_date',
            'avg_satisfaction',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PlayerPreferenceSubmissionSerializer(serializers.Serializer):
    phone = serializers.CharField(
        max_length=20,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text='手机号（匿名玩家可不填）'
    )
    name = serializers.CharField(
        max_length=100,
        required=True,
        help_text='玩家姓名'
    )
    preference_tags = serializers.ListField(
        child=serializers.ChoiceField(choices=PREFERENCE_TAGS),
        required=False,
        default=list,
        help_text='偏好标签列表'
    )
    horror_tolerance = serializers.IntegerField(
        min_value=0,
        max_value=3,
        required=False,
        default=0,
        help_text='恐怖耐受度 0-3'
    )
    accept_reverse = serializers.BooleanField(
        required=False,
        default=False,
        help_text='是否接受反串'
    )

    def validate_preference_tags(self, value):
        validate_preference_tags(value)
        return value

    def validate(self, attrs):
        phone = attrs.get('phone')
        name = attrs.get('name')
        if not phone and not name:
            raise serializers.ValidationError({
                'phone': '匿名玩家必须填写姓名',
                'name': '匿名玩家必须填写姓名',
            })
        return attrs

    def save(self, **kwargs):
        validated_data = self.validated_data
        phone = validated_data.get('phone')
        name = validated_data.get('name')

        profile = None
        if phone:
            profile = PlayerProfile.objects.filter(phone=phone).first()

        if profile is None:
            profile = PlayerProfile.objects.create(
                phone=phone if phone else None,
                name=name,
                preference_tags=validated_data.get('preference_tags', []),
                horror_tolerance=validated_data.get('horror_tolerance', 0),
                accept_reverse=validated_data.get('accept_reverse', False),
            )
        else:
            update_fields = []
            if name and not profile.name:
                profile.name = name
                update_fields.append('name')
            new_tags = validated_data.get('preference_tags', [])
            if new_tags:
                existing_tags = set(profile.preference_tags or [])
                merged_tags = list(existing_tags | set(new_tags))
                profile.preference_tags = merged_tags
                update_fields.append('preference_tags')
            if 'horror_tolerance' in validated_data:
                profile.horror_tolerance = validated_data['horror_tolerance']
                update_fields.append('horror_tolerance')
            if 'accept_reverse' in validated_data:
                profile.accept_reverse = validated_data['accept_reverse']
                update_fields.append('accept_reverse')
            if update_fields:
                update_fields.append('updated_at')
                profile.save(update_fields=update_fields)

        return profile


class RoleAssignmentSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(
        source='role.name',
        read_only=True
    )
    script_name = serializers.CharField(
        source='role.script.name',
        read_only=True
    )
    player_profile_name = serializers.CharField(
        source='player_profile.name',
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = RoleAssignment
        fields = [
            'id',
            'schedule',
            'player_profile',
            'player_profile_name',
            'player_name',
            'player_phone',
            'role',
            'role_name',
            'script_name',
            'match_score',
            'is_manual_adjusted',
            'satisfaction',
            'assigned_at',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'assigned_at']

    def validate_match_score(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError('匹配度必须在0-100之间')
        return value

    def validate_satisfaction(self, value):
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError('满意度必须在1-5之间')
        return value

    def validate(self, attrs):
        schedule = attrs.get('schedule')
        role = attrs.get('role')
        if schedule and role:
            if schedule.script_id and role.script_id != schedule.script_id:
                raise serializers.ValidationError(
                    '角色必须属于场次关联的剧本'
                )
        return attrs


class RoleAssignmentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleAssignment
        fields = [
            'schedule',
            'player_profile',
            'player_name',
            'player_phone',
            'role',
            'match_score',
            'is_manual_adjusted',
            'satisfaction',
        ]

    def validate_match_score(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError('匹配度必须在0-100之间')
        return value

    def validate_satisfaction(self, value):
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError('满意度必须在1-5之间')
        return value


class RoleAssignmentBatchCreateSerializer(serializers.Serializer):
    schedule_id = serializers.IntegerField(required=True, help_text='场次ID')
    assignments = RoleAssignmentCreateSerializer(many=True, required=True)

    def validate_schedule_id(self, value):
        if not Schedule.objects.filter(id=value).exists():
            raise serializers.ValidationError('场次不存在')
        return value

    def validate(self, attrs):
        schedule_id = attrs.get('schedule_id')
        assignments_data = attrs.get('assignments', [])

        try:
            schedule = Schedule.objects.get(id=schedule_id)
        except Schedule.DoesNotExist:
            raise serializers.ValidationError({'schedule_id': '场次不存在'})

        role_ids = [a.get('role') for a in assignments_data if a.get('role')]
        if len(role_ids) != len(set(role_ids)):
            raise serializers.ValidationError(
                {'assignments': '同一角色不能分配给多个玩家'}
            )

        if schedule.script_id:
            valid_role_ids = list(Role.objects.filter(
                script_id=schedule.script_id
            ).values_list('id', flat=True))
            for rid in role_ids:
                if rid not in valid_role_ids:
                    raise serializers.ValidationError(
                        {'assignments': f'角色ID {rid} 不属于该场次的剧本'}
                    )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        schedule_id = validated_data['schedule_id']
        assignments_data = validated_data['assignments']

        RoleAssignment.objects.filter(schedule_id=schedule_id).delete()

        created = []
        for data in assignments_data:
            assignment = RoleAssignment.objects.create(**data)
            created.append(assignment)

            if assignment.player_profile_id and assignment.satisfaction:
                try:
                    profile = PlayerProfile.objects.get(
                        id=assignment.player_profile_id
                    )
                    script_id = None
                    if assignment.role_id:
                        script_id = assignment.role.script_id
                    profile.add_history_role(
                        script_id=script_id,
                        role_id=assignment.role_id,
                        role_name=assignment.role.name if assignment.role_id else '',
                        satisfaction=assignment.satisfaction,
                    )
                except PlayerProfile.DoesNotExist:
                    pass

        return created


class RoleMatchPlayerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=True, help_text='玩家姓名')
    phone = serializers.CharField(
        max_length=20,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text='手机号'
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text='偏好标签列表'
    )
    horror_tolerance = serializers.IntegerField(
        min_value=0,
        max_value=3,
        required=False,
        default=0,
        help_text='恐怖耐受度 0-3'
    )
    accept_reverse = serializers.BooleanField(
        required=False,
        default=False,
        help_text='是否接受反串'
    )
    gender = serializers.CharField(
        max_length=10,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text='性别: male/female/other'
    )
    player_profile_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='关联的玩家档案ID'
    )


class RoleMatchRequestSerializer(serializers.Serializer):
    schedule_id = serializers.IntegerField(required=True, help_text='场次ID')
    players = RoleMatchPlayerSerializer(many=True, required=True)

    def validate_schedule_id(self, value):
        if not Schedule.objects.filter(id=value).exists():
            raise serializers.ValidationError('场次不存在')
        return value

    def validate(self, attrs):
        schedule_id = attrs.get('schedule_id')
        players_data = attrs.get('players', [])

        try:
            schedule = Schedule.objects.select_related('script').get(id=schedule_id)
        except Schedule.DoesNotExist:
            raise serializers.ValidationError({'schedule_id': '场次不存在'})

        if not schedule.script_id:
            raise serializers.ValidationError(
                {'schedule_id': '场次尚未关联剧本，无法匹配角色'}
            )

        roles_count = Role.objects.filter(script_id=schedule.script_id).count()
        if roles_count == 0:
            raise serializers.ValidationError(
                {'schedule_id': '该剧本尚未配置角色'}
            )

        if len(players_data) > roles_count:
            raise serializers.ValidationError(
                {'players': f'玩家数量({len(players_data)})超过角色数量({roles_count})'}
            )

        return attrs

    def execute_match(self):
        validated = self.validated_data
        schedule_id = validated['schedule_id']
        players_data = validated['players']

        schedule = Schedule.objects.select_related('script').get(id=schedule_id)
        script = schedule.script
        roles_qs = Role.objects.filter(script_id=script.id).order_by('id')

        match_roles = [
            MatchRole(
                role_id=role.id,
                role_name=role.name,
                personality_tags=list(role.personality_tags or []),
                suggested_gender=role.suggested_gender,
            )
            for role in roles_qs
        ]

        match_players = []
        for pdata in players_data:
            profile = None
            history_roles = []
            profile_id = pdata.get('player_profile_id')
            phone = pdata.get('phone')

            if profile_id:
                try:
                    profile = PlayerProfile.objects.get(id=profile_id)
                    history_roles = list(profile.history_roles or [])
                except PlayerProfile.DoesNotExist:
                    pass

            if profile is None and phone:
                profile = PlayerProfile.objects.filter(phone=phone).first()
                if profile:
                    history_roles = list(profile.history_roles or [])

            tags = list(pdata.get('tags', []))
            if profile and profile.preference_tags:
                existing_tags = set(tags)
                for pt in profile.preference_tags:
                    existing_tags.add(pt)
                tags = list(existing_tags)

            horror_tolerance = pdata.get('horror_tolerance', 0)
            if profile:
                horror_tolerance = max(horror_tolerance, profile.horror_tolerance or 0)

            accept_reverse = pdata.get('accept_reverse', False)
            if profile:
                accept_reverse = accept_reverse or profile.accept_reverse

            match_players.append(MatchPlayer(
                name=pdata['name'],
                phone=pdata.get('phone'),
                tags=tags,
                horror_tolerance=horror_tolerance,
                accept_reverse=accept_reverse,
                player_profile_id=profile.id if profile else pdata.get('player_profile_id'),
                gender=pdata.get('gender'),
                history_roles=history_roles,
            ))

        is_horror = script.type == ScriptType.HORROR

        result = run_role_matching(
            players=match_players,
            roles=match_roles,
            is_horror_script=is_horror,
            script_type=script.type,
        )

        return result, schedule, script, match_roles


class MatchBreakdownSerializer(serializers.Serializer):
    a_score = serializers.FloatField(help_text='性格标签匹配得分')
    b_score = serializers.FloatField(help_text='性别匹配得分')
    c_score = serializers.FloatField(help_text='恐怖接受度得分')
    d_score = serializers.FloatField(help_text='历史角色去重得分')


class MatchAssignmentSerializer(serializers.Serializer):
    player_name = serializers.CharField()
    player_phone = serializers.CharField(allow_null=True, allow_blank=True)
    role_id = serializers.IntegerField()
    role_name = serializers.CharField()
    match_score = serializers.FloatField()
    breakdown = MatchBreakdownSerializer()


class RoleMatchResultSerializer(serializers.Serializer):
    assignments = MatchAssignmentSerializer(many=True)
    alternative_suggestions = serializers.ListField(
        child=MatchAssignmentSerializer(many=True)
    )
    total_score = serializers.FloatField(help_text='总匹配分')
    avg_score = serializers.FloatField(help_text='平均匹配分')


class SatisfactionUpdateSerializer(serializers.Serializer):
    satisfaction = serializers.IntegerField(
        min_value=1,
        max_value=5,
        required=True,
        help_text='满意度 1-5星'
    )

    def update(self, instance, validated_data):
        instance.satisfaction = validated_data['satisfaction']
        instance.save(update_fields=['satisfaction'])

        if instance.player_profile_id and instance.role_id:
            try:
                profile = PlayerProfile.objects.get(id=instance.player_profile_id)
                script_id = instance.role.script_id
                already_exists = False
                for hr in profile.history_roles:
                    if (hr.get('script_id') == script_id and
                            hr.get('role_id') == instance.role_id):
                        hr['satisfaction'] = instance.satisfaction
                        already_exists = True
                        break
                if not already_exists:
                    profile.add_history_role(
                        script_id=script_id,
                        role_id=instance.role_id,
                        role_name=instance.role.name,
                        satisfaction=instance.satisfaction,
                    )
                else:
                    profile.save(update_fields=['history_roles', 'updated_at'])
            except PlayerProfile.DoesNotExist:
                pass

        return instance
