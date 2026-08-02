from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.exceptions import PermissionDenied, ValidationError, APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler
from django.db.utils import IntegrityError


class LoginFailedException(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = '用户名或密码错误'
    default_code = 'login_failed'


class AccountLockedException(APIException):
    status_code = status.HTTP_423_LOCKED
    default_detail = '账户已被暂时锁定，请稍后再试'
    default_code = 'account_locked'

    def __init__(self, unlock_time=None, detail=None, code=None):
        if unlock_time:
            detail = detail or f'账户已被锁定，请于 {unlock_time.strftime("%Y-%m-%d %H:%M:%S")} 后再试'
        super().__init__(detail, code)


class AccountDisabledException(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = '账户已被禁用，请联系管理员'
    default_code = 'account_disabled'


class FirstLoginException(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = '首次登录需要修改密码'
    default_code = 'first_login'


class InvalidTokenException(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = '无效的token'
    default_code = 'invalid_token'


class BusinessException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = '业务异常'
    default_code = 'business_error'

    def __init__(self, detail=None, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail, code)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        response.data = _format_exception_data(exc, response)
        return response

    if isinstance(exc, Http404):
        return Response(
            {
                'code': 'not_found',
                'message': '资源不存在',
                'data': None,
                'timestamp': datetime.now().isoformat(),
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                'code': 'validation_error',
                'message': '数据验证失败',
                'data': exc.messages if hasattr(exc, 'messages') else str(exc),
                'timestamp': datetime.now().isoformat(),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        return Response(
            {
                'code': 'integrity_error',
                'message': '数据完整性错误',
                'data': str(exc),
                'timestamp': datetime.now().isoformat(),
            },
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, PermissionError):
        return Response(
            {
                'code': 'permission_denied',
                'message': '权限不足',
                'data': str(exc),
                'timestamp': datetime.now().isoformat(),
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response(
        {
            'code': 'internal_server_error',
            'message': '服务器内部错误',
            'data': str(exc),
            'timestamp': datetime.now().isoformat(),
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _format_exception_data(exc, response):
    code = getattr(exc, 'default_code', 'error')
    if isinstance(exc, exceptions.ValidationError):
        code = 'validation_error'
        message = '数据验证失败'
        errors = exc.detail
    elif isinstance(exc, exceptions.AuthenticationFailed):
        code = 'authentication_failed'
        message = str(exc.detail) if exc.detail else '认证失败'
        errors = None
    elif isinstance(exc, exceptions.NotAuthenticated):
        code = 'not_authenticated'
        message = str(exc.detail) if exc.detail else '请先登录'
        errors = None
    elif isinstance(exc, exceptions.PermissionDenied):
        code = 'permission_denied'
        message = str(exc.detail) if exc.detail else '权限不足'
        errors = None
    elif isinstance(exc, exceptions.NotFound):
        code = 'not_found'
        message = str(exc.detail) if exc.detail else '资源不存在'
        errors = None
    elif isinstance(exc, exceptions.MethodNotAllowed):
        code = 'method_not_allowed'
        message = str(exc.detail) if exc.detail else '方法不允许'
        errors = None
    elif isinstance(exc, exceptions.Throttled):
        code = 'throttled'
        message = str(exc.detail) if exc.detail else '请求过于频繁，请稍后再试'
        errors = None
    else:
        code = getattr(exc, 'default_code', code)
        message = str(exc.detail) if exc.detail else '请求错误'
        errors = None

    result = {
        'code': code,
        'message': message,
        'timestamp': datetime.now().isoformat(),
    }

    if errors is not None:
        result['errors'] = errors
    else:
        result['data'] = None

    return result
