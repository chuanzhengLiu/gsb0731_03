import copy
import json
import logging
import queue
import re
import threading
import time

from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone

from .models import AuditAction, AuditStatus, AuditTargetType


logger = logging.getLogger(__name__)


_audit_context = threading.local()


SENSITIVE_FIELDS = {
    'password', 'password1', 'password2', 'old_password', 'new_password',
    'token', 'access_token', 'refresh_token', 'secret', 'private_key',
    'credit_card', 'cvv', 'ssn', 'phone', 'email', 'id_card',
}


SENSITIVE_PATTERNS = [
    re.compile(r'password', re.IGNORECASE),
    re.compile(r'token', re.IGNORECASE),
    re.compile(r'secret', re.IGNORECASE),
    re.compile(r'private[_-]?key', re.IGNORECASE),
    re.compile(r'credit[_-]?card', re.IGNORECASE),
]


EXCLUDED_PATH_PREFIXES = [
    '/static/',
    '/media/',
    '/favicon.ico',
    '/swagger/',
    '/redoc/',
    '/api-auth/',
    '/api/auth/refresh/',
    '/api/auth/token/refresh/',
    '/health/',
    '/healthcheck/',
]


WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}


LOGIN_PATTERNS = [
    re.compile(r'^/api/auth/login/?$', re.IGNORECASE),
    re.compile(r'^/api/auth/token/?$', re.IGNORECASE),
    re.compile(r'^/api/accounts/login/?$', re.IGNORECASE),
    re.compile(r'^/admin/login/?$', re.IGNORECASE),
]

LOGOUT_PATTERNS = [
    re.compile(r'^/api/auth/logout/?$', re.IGNORECASE),
    re.compile(r'^/api/accounts/logout/?$', re.IGNORECASE),
    re.compile(r'^/admin/logout/?$', re.IGNORECASE),
]


PATH_TARGET_TYPE_MAP = [
    (re.compile(r'/api/accounts/users/'), AuditTargetType.USER),
    (re.compile(r'/api/stores/'), AuditTargetType.STORE),
    (re.compile(r'/api/rooms/'), AuditTargetType.ROOM),
    (re.compile(r'/api/scripts/'), AuditTargetType.SCRIPT),
    (re.compile(r'/api/dms/profiles/'), AuditTargetType.DM_PROFILE),
    (re.compile(r'/api/dms/skills/'), AuditTargetType.DM_SKILL),
    (re.compile(r'/api/dms/availabilities/'), AuditTargetType.DM_AVAILABILITY),
    (re.compile(r'/api/dms/leaves/'), AuditTargetType.DM_LEAVE),
    (re.compile(r'/api/bookings/'), AuditTargetType.BOOKING),
    (re.compile(r'/api/schedules/'), AuditTargetType.SCHEDULE),
    (re.compile(r'/api/audit/logs/'), AuditTargetType.AUDIT_LOG),
    (re.compile(r'/api/reviews/'), AuditTargetType.REVIEW),
    (re.compile(r'/api/players/profiles/'), AuditTargetType.PLAYER_PROFILE),
    (re.compile(r'/api/role-assignments/'), AuditTargetType.ROLE_ASSIGNMENT),
]


class AuditLogQueue:
    def __init__(self, max_size=1000, flush_interval=1.0, batch_size=100):
        self._queue = queue.Queue(maxsize=max_size)
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._stop_event = threading.Event()
        self._worker_thread = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._stop_event.clear()
                self._worker_thread = threading.Thread(
                    target=self._run,
                    daemon=True,
                    name='AuditLogWorker'
                )
                self._worker_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

    def put(self, log_data):
        try:
            self._queue.put_nowait(log_data)
        except queue.Full:
            logger.warning('Audit log queue is full, dropping log entry')

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._flush_batch()
            except Exception as e:
                logger.error(f'Error flushing audit logs: {e}', exc_info=True)
            time.sleep(self._flush_interval)
        self._flush_batch()

    def _flush_batch(self):
        from .models import AuditLog

        batch = []
        try:
            for _ in range(self._batch_size):
                try:
                    log_data = self._queue.get_nowait()
                    batch.append(log_data)
                except queue.Empty:
                    break

            if not batch:
                return

            logs_to_create = []
            for data in batch:
                try:
                    logs_to_create.append(AuditLog(**data))
                except Exception as e:
                    logger.error(f'Invalid audit log data: {e}, data: {data}')

            if logs_to_create:
                AuditLog.objects.bulk_create(logs_to_create, batch_size=self._batch_size)
                logger.debug(f'Flushed {len(logs_to_create)} audit logs')

        except Exception as e:
            logger.error(f'Error during audit log batch flush: {e}', exc_info=True)


_audit_queue = AuditLogQueue()
_queue_started = False
_queue_start_lock = threading.Lock()


def _ensure_queue_started():
    global _queue_started
    if not _queue_started:
        with _queue_start_lock:
            if not _queue_started:
                _audit_queue.start()
                _queue_started = True


def _mask_sensitive(data):
    if data is None:
        return data
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, (dict, list)):
                return json.dumps(_mask_sensitive(parsed), ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return data
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            is_sensitive = key_lower in SENSITIVE_FIELDS
            if not is_sensitive:
                for pattern in SENSITIVE_PATTERNS:
                    if pattern.search(key):
                        is_sensitive = True
                        break
            if is_sensitive:
                result[key] = '***'
            else:
                result[key] = _mask_sensitive(value)
        return result
    if isinstance(data, list):
        return [_mask_sensitive(item) for item in data]
    return data


def _get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
    return ip


def _get_user_agent(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    return ua[:500] if len(ua) > 500 else ua


def _get_target_id_from_path(path):
    match = re.search(r'/(\d+)(?:/|$)', path)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _infer_target_type(path):
    for pattern, target_type in PATH_TARGET_TYPE_MAP:
        if pattern.search(path):
            return target_type
    return AuditTargetType.OTHER


def _infer_action(method, path):
    for pattern in LOGIN_PATTERNS:
        if pattern.match(path):
            return AuditAction.LOGIN
    for pattern in LOGOUT_PATTERNS:
        if pattern.match(path):
            return AuditAction.LOGOUT

    if method == 'POST':
        return AuditAction.CREATE
    elif method in ('PUT', 'PATCH'):
        return AuditAction.UPDATE
    elif method == 'DELETE':
        return AuditAction.DELETE
    return AuditAction.UPDATE


def _is_excluded_path(path):
    for prefix in EXCLUDED_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _is_login_request(path):
    for pattern in LOGIN_PATTERNS:
        if pattern.match(path):
            return True
    return False


def _is_logout_request(path):
    for pattern in LOGOUT_PATTERNS:
        if pattern.match(path):
            return True
    return False


def _get_request_body(request):
    try:
        if hasattr(request, 'body') and request.body:
            body_str = request.body.decode('utf-8', errors='replace')
            try:
                parsed = json.loads(body_str)
                return _mask_sensitive(parsed)
            except (json.JSONDecodeError, TypeError):
                return _mask_sensitive(body_str)
    except Exception:
        pass
    return None


def _get_response_body(response):
    try:
        if hasattr(response, 'data'):
            return _mask_sensitive(copy.deepcopy(response.data))
        if hasattr(response, 'content') and response.content:
            content_str = response.content.decode('utf-8', errors='replace')
            try:
                parsed = json.loads(content_str)
                return _mask_sensitive(parsed)
            except (json.JSONDecodeError, TypeError):
                return _mask_sensitive(content_str)
    except Exception:
        pass
    return None


def set_audit_context(action=None, target_type=None, target_id=None,
                      target_name=None, extra_details=None, store_id=None,
                      status=None, failure_reason=None, skip_log=False):
    context = getattr(_audit_context, 'data', {})
    if action is not None:
        context['action'] = action
    if target_type is not None:
        context['target_type'] = target_type
    if target_id is not None:
        context['target_id'] = target_id
    if target_name is not None:
        context['target_name'] = target_name
    if extra_details is not None:
        existing_details = context.get('details', {})
        existing_extra = existing_details.get('extra', {})
        if isinstance(extra_details, dict):
            existing_extra.update(extra_details)
        existing_details['extra'] = existing_extra
        context['details'] = existing_details
    if store_id is not None:
        context['store_id'] = store_id
    if status is not None:
        context['status'] = status
    if failure_reason is not None:
        context['failure_reason'] = failure_reason
    if skip_log:
        context['skip_log'] = True
    _audit_context.data = context


def clear_audit_context():
    if hasattr(_audit_context, 'data'):
        del _audit_context.data


def _get_old_data_for_update(request):
    try:
        resolver_match = getattr(request, 'resolver_match', None)
        if not resolver_match:
            return None

        kwargs = resolver_match.kwargs or {}
        pk = kwargs.get('pk') or kwargs.get('id')
        if pk is None:
            return None

        view_class = getattr(resolver_match.func, 'cls', None)
        if view_class is None:
            return None

        queryset = getattr(view_class, 'queryset', None)
        if queryset is None:
            return None

        model = queryset.model
        try:
            obj = model.objects.get(pk=pk)
            data = {}
            for field in model._meta.fields:
                field_name = field.name
                if field_name in ('password',):
                    continue
                value = getattr(obj, field_name, None)
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                elif hasattr(value, 'id'):
                    value = value.id
                data[field_name] = value
            return data
        except Exception:
            return None
    except Exception:
        return None


def _compare_changes(old_data, new_data):
    if not old_data or not new_data or not isinstance(new_data, dict):
        return {}
    changes = {}
    for key, new_value in new_data.items():
        if key in old_data:
            old_value = old_data[key]
            if old_value != new_value:
                changes[key] = {
                    'old': old_value,
                    'new': new_value,
                }
    return changes


def log_audit(request, action, target_type, target_id=None, target_name=None,
              details=None, status=AuditStatus.SUCCESS, failure_reason=None):
    _ensure_queue_started()

    user = getattr(request, 'user', None)
    user_id = None
    username = ''
    store_id = None

    if user and user.is_authenticated:
        user_id = user.id
        username = getattr(user, 'username', '') or ''
        user_store = getattr(user, 'store', None)
        if user_store:
            store_id = getattr(user_store, 'id', None)

    log_details = details if isinstance(details, dict) else {}
    if 'changes' not in log_details:
        log_details['changes'] = {}
    if 'extra' not in log_details:
        log_details['extra'] = {}

    log_data = {
        'user_id': user_id,
        'username': username,
        'action': action,
        'target_type': target_type,
        'target_id': target_id,
        'target_name': target_name,
        'store_id': store_id,
        'details': log_details,
        'ip_address': _get_client_ip(request),
        'user_agent': _get_user_agent(request),
        'status': status,
        'failure_reason': failure_reason,
        'created_at': timezone.now(),
    }

    _audit_queue.put(log_data)
    return log_data


class AuditLogMiddleware(MiddlewareMixin):
    def __init__(self, get_response=None):
        super().__init__(get_response)
        _ensure_queue_started()

    def process_request(self, request):
        clear_audit_context()
        _audit_context.data = {}

        if _is_excluded_path(request.path):
            return None

        method = request.method.upper()
        path = request.path

        is_write = method in WRITE_METHODS
        is_auth = _is_login_request(path) or _is_logout_request(path)

        if not is_write and not is_auth:
            return None

        context = {}

        if method in ('PUT', 'PATCH'):
            old_data = _get_old_data_for_update(request)
            if old_data:
                context['_old_data'] = old_data

        context['_request_body'] = _get_request_body(request)
        context['_method'] = method
        context['_path'] = path

        _audit_context.data.update(context)
        return None

    def process_response(self, request, response):
        try:
            context = getattr(_audit_context, 'data', {})

            if not context:
                return response

            if context.get('skip_log'):
                return response

            path = request.path
            if _is_excluded_path(path):
                return response

            method = request.method.upper()
            is_write = method in WRITE_METHODS
            is_login = _is_login_request(path)
            is_logout = _is_logout_request(path)

            if not is_write and not is_login and not is_logout:
                return response

            status_code = response.status_code
            is_success = 200 <= status_code < 400

            user = getattr(request, 'user', None)
            user_id = None
            username = ''
            store_id = None

            if user and user.is_authenticated:
                user_id = user.id
                username = getattr(user, 'username', '') or ''
                user_store = getattr(user, 'store', None)
                if user_store:
                    store_id = getattr(user_store, 'id', None)

            action = context.get('action')
            if not action:
                if is_login and is_success:
                    action = AuditAction.LOGIN
                elif is_logout and is_success:
                    action = AuditAction.LOGOUT
                else:
                    action = _infer_action(method, path)

            target_type = context.get('target_type')
            if not target_type:
                target_type = _infer_target_type(path)

            target_id = context.get('target_id')
            if target_id is None:
                target_id = _get_target_id_from_path(path)

            target_name = context.get('target_name')

            if 'store_id' in context:
                store_id = context['store_id']

            details = context.get('details', {})
            if not isinstance(details, dict):
                details = {}
            if 'changes' not in details:
                details['changes'] = {}
            if 'extra' not in details:
                details['extra'] = {}

            request_body = context.get('_request_body')
            if request_body is not None:
                details['extra']['request_body'] = request_body

            response_body = _get_response_body(response)
            if response_body is not None:
                if isinstance(response_body, dict) and 'id' in response_body and target_id is None:
                    target_id = response_body['id']
                if isinstance(response_body, dict) and 'username' in response_body and target_type == AuditTargetType.USER and not target_name:
                    target_name = response_body['username']
                if isinstance(response_body, dict) and 'name' in response_body and not target_name:
                    target_name = response_body['name']
                details['extra']['response_body'] = response_body

            if method in ('PUT', 'PATCH') and is_success:
                old_data = context.get('_old_data')
                new_data = request_body if isinstance(request_body, dict) else None
                if not new_data and isinstance(response_body, dict):
                    new_data = response_body
                if old_data and new_data:
                    changes = _compare_changes(old_data, new_data)
                    if changes:
                        details['changes'] = changes

            if not is_login and user_id is None and isinstance(response_body, dict):
                if 'user_id' in response_body:
                    user_id = response_body['user_id']
                if 'id' in response_body and target_type == AuditTargetType.USER:
                    user_id = response_body['id']
                if 'username' in response_body and not username:
                    username = response_body['username']

            details['extra']['method'] = method
            details['extra']['path'] = path
            details['extra']['status_code'] = status_code

            query_params = dict(request.GET.lists()) if request.GET else {}
            if query_params:
                details['extra']['query_params'] = _mask_sensitive(query_params)

            audit_status = context.get('status')
            if not audit_status:
                audit_status = AuditStatus.SUCCESS if is_success else AuditStatus.FAILED

            audit_failure_reason = context.get('failure_reason')
            if not audit_failure_reason and not is_success:
                if isinstance(response_body, dict) and 'detail' in response_body:
                    reason = str(response_body['detail'])
                    audit_failure_reason = reason[:500] if len(reason) > 500 else reason
                elif isinstance(response_body, dict) and 'message' in response_body:
                    reason = str(response_body['message'])
                    audit_failure_reason = reason[:500] if len(reason) > 500 else reason

            _ensure_queue_started()
            log_data = {
                'user_id': user_id,
                'username': username,
                'action': action,
                'target_type': target_type,
                'target_id': target_id,
                'target_name': target_name,
                'store_id': store_id,
                'details': details,
                'ip_address': _get_client_ip(request),
                'user_agent': _get_user_agent(request),
                'status': audit_status,
                'failure_reason': audit_failure_reason,
                'created_at': timezone.now(),
            }
            _audit_queue.put(log_data)

        except Exception as e:
            logger.error(f'Error in AuditLogMiddleware.process_response: {e}', exc_info=True)
        finally:
            clear_audit_context()

        return response

    def process_exception(self, request, exception):
        try:
            context = getattr(_audit_context, 'data', {})
            if not context:
                return None

            if context.get('skip_log'):
                return None

            path = request.path
            if _is_excluded_path(path):
                return None

            method = request.method.upper()
            is_write = method in WRITE_METHODS
            is_login = _is_login_request(path)
            is_logout = _is_logout_request(path)

            if not is_write and not is_login and not is_logout:
                return None

            user = getattr(request, 'user', None)
            user_id = None
            username = ''
            store_id = None

            if user and user.is_authenticated:
                user_id = user.id
                username = getattr(user, 'username', '') or ''
                user_store = getattr(user, 'store', None)
                if user_store:
                    store_id = getattr(user_store, 'id', None)

            action = context.get('action') or _infer_action(method, path)
            target_type = context.get('target_type') or _infer_target_type(path)
            target_id = context.get('target_id') or _get_target_id_from_path(path)
            target_name = context.get('target_name')

            if 'store_id' in context:
                store_id = context['store_id']

            details = context.get('details', {})
            if not isinstance(details, dict):
                details = {}
            if 'changes' not in details:
                details['changes'] = {}
            if 'extra' not in details:
                details['extra'] = {}

            request_body = context.get('_request_body')
            if request_body is not None:
                details['extra']['request_body'] = request_body

            details['extra']['method'] = method
            details['extra']['path'] = path
            details['extra']['exception'] = str(exception)[:500]

            audit_status = context.get('status') or AuditStatus.FAILED
            audit_failure_reason = context.get('failure_reason') or str(exception)[:500]

            _ensure_queue_started()
            log_data = {
                'user_id': user_id,
                'username': username,
                'action': action,
                'target_type': target_type,
                'target_id': target_id,
                'target_name': target_name,
                'store_id': store_id,
                'details': details,
                'ip_address': _get_client_ip(request),
                'user_agent': _get_user_agent(request),
                'status': audit_status,
                'failure_reason': audit_failure_reason,
                'created_at': timezone.now(),
            }
            _audit_queue.put(log_data)

        except Exception as e:
            logger.error(f'Error in AuditLogMiddleware.process_exception: {e}', exc_info=True)
        finally:
            clear_audit_context()

        return None
