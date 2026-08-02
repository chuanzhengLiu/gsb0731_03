import re

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .exceptions import (
    LoginFailedException,
    AccountDisabledException,
    FirstLoginException,
    BusinessException,
)
from .models import User, UserRole


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    store_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'name',
            'role',
            'role_display',
            'store',
            'store_id',
            'store_name',
            'phone',
            'first_login',
            'is_active',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'created_at',
            'first_login',
        ]

    def get_store_name(self, obj):
        if obj.store:
            return obj.store.name
        return None

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if 'store' in ret and ret['store'] is not None:
            ret.pop('store')
        return ret


class UserDetailSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    store_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'name',
            'role',
            'role_display',
            'store_id',
            'store_name',
            'phone',
            'first_login',
            'is_active',
            'is_staff',
            'is_superuser',
            'created_at',
            'last_login',
        ]
        read_only_fields = fields

    def get_store_name(self, obj):
        if obj.store:
            return obj.store.name
        return None


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(
        max_length=150,
        required=True,
        error_messages={'required': '用户名不能为空'},
    )
    password = serializers.CharField(
        write_only=True,
        required=True,
        error_messages={'required': '密码不能为空'},
    )

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        user = authenticate(username=username, password=password)

        if not user:
            raise LoginFailedException()

        if not user.is_active:
            raise AccountDisabledException()

        attrs['user'] = user
        return attrs


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        error_messages={'required': '密码不能为空'},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        error_messages={'required': '确认密码不能为空'},
    )

    class Meta:
        model = User
        fields = [
            'username',
            'password',
            'confirm_password',
            'name',
            'role',
            'store',
            'phone',
        ]
        extra_kwargs = {
            'name': {'required': False},
            'role': {'required': True},
            'store': {'required': False, 'allow_null': True},
            'phone': {'required': False},
        }

    def validate_username(self, value):
        if not re.match(r'^[a-zA-Z0-9_]{3,150}$', value):
            raise serializers.ValidationError('用户名只能包含字母、数字和下划线，长度3-150位')
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('该用户名已被使用')
        return value

    def validate_phone(self, value):
        if value:
            if not re.match(r'^1[3-9]\d{9}$', value):
                raise serializers.ValidationError('请输入正确的手机号')
        return value

    def validate_role(self, value):
        valid_roles = [r.value for r in UserRole]
        if value not in valid_roles:
            raise serializers.ValidationError('无效的角色')
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('confirm_password'):
            raise serializers.ValidationError({'confirm_password': '两次输入的密码不一致'})

        role = attrs.get('role')
        store = attrs.get('store')

        if role != UserRole.PLATFORM_ADMIN and store is None:
            request = self.context.get('request')
            if request and hasattr(request, 'user') and request.user.is_authenticated:
                if not request.user.is_platform_admin():
                    attrs['store'] = request.user.store
            if attrs.get('store') is None:
                raise serializers.ValidationError({'store': '非平台管理员必须关联门店'})

        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        password = validated_data.pop('password')

        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            if not request.user.is_platform_admin():
                validated_data['store'] = request.user.store
                if validated_data.get('role') in [UserRole.PLATFORM_ADMIN, UserRole.STORE_MANAGER]:
                    raise BusinessException('您无权创建该角色')

        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        write_only=True,
        required=True,
        error_messages={'required': '原密码不能为空'},
    )
    new_password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        error_messages={'required': '新密码不能为空'},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        error_messages={'required': '确认密码不能为空'},
    )

    def validate(self, attrs):
        if attrs.get('new_password') != attrs.get('confirm_password'):
            raise serializers.ValidationError({'confirm_password': '两次输入的密码不一致'})

        if attrs.get('old_password') == attrs.get('new_password'):
            raise serializers.ValidationError({'new_password': '新密码不能与原密码相同'})

        user = self.context.get('request').user
        if not user.check_password(attrs.get('old_password')):
            raise serializers.ValidationError({'old_password': '原密码错误'})

        return attrs


class PasswordResetSerializer(serializers.Serializer):
    username = serializers.CharField(
        max_length=150,
        required=True,
        error_messages={'required': '用户名不能为空'},
    )
    new_password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        error_messages={'required': '新密码不能为空'},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        error_messages={'required': '确认密码不能为空'},
    )

    def validate(self, attrs):
        if attrs.get('new_password') != attrs.get('confirm_password'):
            raise serializers.ValidationError({'confirm_password': '两次输入的密码不一致'})

        try:
            user = User.objects.get(username=attrs.get('username'))
        except User.DoesNotExist:
            raise serializers.ValidationError({'username': '用户不存在'})

        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            if not request.user.is_platform_admin() and not request.user.is_store_manager():
                if request.user.store_id != user.store_id:
                    raise serializers.ValidationError('您无权重置该用户密码')

        attrs['user'] = user
        return attrs


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['role'] = user.role
        token['store_id'] = user.store_id
        token['name'] = user.name
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        if not self.user.is_active:
            raise AccountDisabledException()

        refresh = data.pop('refresh')
        access = data.pop('access')

        data['code'] = 'success'
        data['message'] = '登录成功'
        data['data'] = {
            'access_token': access,
            'refresh_token': refresh,
            'user': UserDetailSerializer(self.user).data,
            'first_login': self.user.first_login,
        }
        data['timestamp'] = ''

        if self.user.first_login:
            data['message'] = '首次登录，请修改密码'
            data['first_login_required'] = True

        return data
