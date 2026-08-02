from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import update_session_auth_hash
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.db.models import Q
from django_ratelimit.decorators import ratelimit
from django_ratelimit.core import get_usage
from rest_framework import generics, status, views, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.pagination import PageNumberPagination

from .exceptions import (
    LoginFailedException,
    AccountLockedException,
    AccountDisabledException,
    BusinessException,
)
from .models import User, UserRole
from .permissions import (
    IsPlatformAdmin,
    IsAssistantManagerOrAbove,
    StoreScopedPermission,
)
from .serializers import (
    LoginSerializer,
    RegisterSerializer,
    ChangePasswordSerializer,
    PasswordResetSerializer,
    UserSerializer,
    UserDetailSerializer,
    CustomTokenObtainPairSerializer,
)


LOGIN_ATTEMPTS_CACHE_KEY = 'login_attempts:{}'
LOGIN_LOCKOUT_CACHE_KEY = 'login_lockout:{}'
LOGIN_ATTEMPTS_LIMIT = getattr(settings, 'LOGIN_ATTEMPTS_LIMIT', 5)
LOGIN_LOCKOUT_MINUTES = getattr(settings, 'LOGIN_LOCKOUT_MINUTES', 15)


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _get_login_attempts_cache_key(username):
    return LOGIN_ATTEMPTS_CACHE_KEY.format(username.lower())


def _get_login_lockout_cache_key(username):
    return LOGIN_LOCKOUT_CACHE_KEY.format(username.lower())


def _get_login_attempts(username):
    key = _get_login_attempts_cache_key(username)
    return cache.get(key, 0)


def _increment_login_attempts(username):
    key = _get_login_attempts_cache_key(username)
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, LOGIN_LOCKOUT_MINUTES * 60)
    return attempts


def _reset_login_attempts(username):
    cache.delete(_get_login_attempts_cache_key(username))
    cache.delete(_get_login_lockout_cache_key(username))


def _check_account_locked(username):
    key = _get_login_lockout_cache_key(username)
    lockout_until = cache.get(key)
    if lockout_until and timezone.now() < lockout_until:
        return lockout_until
    if lockout_until and timezone.now() >= lockout_until:
        cache.delete(key)
        cache.delete(_get_login_attempts_cache_key(username))
    return None


def _lock_account(username):
    key = _get_login_lockout_cache_key(username)
    lockout_until = timezone.now() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    cache.set(key, lockout_until, LOGIN_LOCKOUT_MINUTES * 60)
    return lockout_until


class LoginView(views.APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ratelimit(key='ip', rate='5/m', method=['POST'], block=False))
    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '')

        if not username or not password:
            raise LoginFailedException('用户名和密码不能为空')

        lockout_until = _check_account_locked(username)
        if lockout_until:
            raise AccountLockedException(unlock_time=lockout_until)

        attempts = _get_login_attempts(username)
        if attempts >= LOGIN_ATTEMPTS_LIMIT:
            lockout_until = _lock_account(username)
            raise AccountLockedException(unlock_time=lockout_until)

        serializer = LoginSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            attempts = _increment_login_attempts(username)
            if attempts >= LOGIN_ATTEMPTS_LIMIT:
                lockout_until = _lock_account(username)
                raise AccountLockedException(unlock_time=lockout_until)
            remaining = LOGIN_ATTEMPTS_LIMIT - attempts
            raise LoginFailedException(
                f'用户名或密码错误，剩余尝试次数：{remaining}'
            )

        user = serializer.validated_data['user']

        lockout_until = _check_account_locked(username)
        if lockout_until:
            raise AccountLockedException(unlock_time=lockout_until)

        if not user.is_active:
            raise AccountDisabledException()

        _reset_login_attempts(username)

        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        return Response({
            'code': 'success',
            'message': '登录成功' if not user.first_login else '首次登录，请修改密码',
            'data': {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'user': UserDetailSerializer(user).data,
                'first_login': user.first_login,
            },
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class LogoutView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            if refresh_token:
                token = RefreshToken(refresh_token)
                try:
                    token.blacklist()
                except Exception:
                    pass
        except Exception:
            pass

        return Response({
            'code': 'success',
            'message': '登出成功',
            'data': None,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class CustomTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            access_token = str(serializer.validated_data['access'])
            refresh_token = str(serializer.validated_data.get('refresh', request.data.get('refresh', '')))

            return Response({
                'code': 'success',
                'message': '刷新成功',
                'data': {
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                },
                'timestamp': timezone.now().isoformat(),
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'code': 'token_refresh_failed',
                'message': str(e) if str(e) else '刷新失败，请重新登录',
                'data': None,
                'timestamp': timezone.now().isoformat(),
            }, status=status.HTTP_401_UNAUTHORIZED)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response({
            'code': 'success',
            'message': '注册成功',
            'data': UserSerializer(user).data,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_201_CREATED)


class ChangePasswordView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])

        if user.first_login:
            user.first_login = False

        user.save()
        update_session_auth_hash(request, user)

        return Response({
            'code': 'success',
            'message': '密码修改成功',
            'data': None,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class PasswordResetView(views.APIView):
    permission_classes = [IsAssistantManagerOrAbove]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']

        if user.is_platform_admin() and not request.user.is_platform_admin():
            raise BusinessException('您无权重置平台管理员密码', status_code=status.HTTP_403_FORBIDDEN)

        user.set_password(serializer.validated_data['new_password'])
        user.first_login = True
        user.save()

        return Response({
            'code': 'success',
            'message': '密码重置成功',
            'data': None,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = UserDetailSerializer(instance)
        return Response({
            'code': 'success',
            'message': '获取成功',
            'data': serializer.data,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        allowed_fields = ['name', 'phone']
        filtered_data = {k: v for k, v in request.data.items() if k in allowed_fields}

        serializer = self.get_serializer(instance, data=filtered_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            'code': 'success',
            'message': '更新成功',
            'data': UserDetailSerializer(instance).data,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class UserListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, StoreScopedPermission]
    serializer_class = UserSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        queryset = User.objects.all().order_by('-created_at')

        user = self.request.user

        if not user.is_platform_admin():
            queryset = queryset.filter(store_id=user.store_id)

        store_id = self.request.query_params.get('store_id')
        if store_id:
            if user.is_platform_admin():
                queryset = queryset.filter(store_id=store_id)
            elif str(user.store_id) != str(store_id):
                queryset = queryset.none()

        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)

        keyword = self.request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                Q(username__icontains=keyword) |
                Q(name__icontains=keyword) |
                Q(phone__icontains=keyword)
            )

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=(str(is_active).lower() == 'true'))

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'code': 'success',
            'message': '获取成功',
            'data': serializer.data,
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)

    def get_paginated_response(self, data):
        return Response({
            'code': 'success',
            'message': '获取成功',
            'data': {
                'results': data,
                'count': self.paginator.page.paginator.count,
                'next': self.paginator.get_next_link(),
                'previous': self.paginator.get_previous_link(),
                'page': self.paginator.page.number,
                'page_size': self.paginator.page.paginator.per_page,
                'total_pages': self.paginator.page.paginator.num_pages,
            },
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, StoreScopedPermission]
    serializer_class = UserSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        queryset = User.objects.all().order_by('-created_at')
        user = self.request.user

        if not user.is_platform_admin():
            queryset = queryset.filter(store_id=user.store_id)

        return queryset

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAssistantManagerOrAbove()]
        return [IsAuthenticated(), StoreScopedPermission()]

    def perform_create(self, serializer):
        user = self.request.user
        validated_data = dict(serializer.validated_data)

        if not user.is_platform_admin():
            validated_data['store'] = user.store
            if validated_data.get('role') in [UserRole.PLATFORM_ADMIN, UserRole.STORE_MANAGER]:
                raise BusinessException('您无权创建该角色')

        serializer.save(**validated_data)

    def perform_update(self, serializer):
        user = self.request.user
        instance = serializer.instance

        if instance.is_platform_admin() and not user.is_platform_admin():
            raise BusinessException('您无权修改平台管理员')

        if not user.is_platform_admin():
            if 'role' in self.request.data:
                new_role = self.request.data.get('role')
                if new_role in [UserRole.PLATFORM_ADMIN, UserRole.STORE_MANAGER]:
                    raise BusinessException('您无权修改为该角色')

        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user

        if instance.is_platform_admin() and not user.is_platform_admin():
            raise BusinessException('您无权删除平台管理员')

        if instance.id == user.id:
            raise BusinessException('您不能删除自己')

        instance.is_active = False
        instance.save()
