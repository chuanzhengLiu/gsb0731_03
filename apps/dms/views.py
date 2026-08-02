from datetime import datetime, timedelta
from calendar import monthrange

from django.db import transaction
from django.db.models import Count, Sum, Q, IntegerField
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import UserRole

from .models import (
    DMProfile,
    DMSkill,
    DMAvailability,
    DMTemporaryUnavailable,
)
from .permissions import (
    DMProfilePermission,
    DMSkillPermission,
    DMAvailabilityPermission,
    DMTemporaryUnavailablePermission,
)
from .filters import (
    DMProfileFilter,
    DMSkillFilter,
    DMAvailabilityFilter,
    DMTemporaryUnavailableFilter,
)
from .serializers import (
    DMProfileSerializer,
    DMProfileListSerializer,
    DMProfileDetailSerializer,
    DMSkillSerializer,
    DMSkillBatchUpdateSerializer,
    DMSetSkillSerializer,
    DMAvailabilitySerializer,
    DMTemporaryUnavailableSerializer,
    DMTemporaryUnavailableApproveSerializer,
    DMWorkloadStatsSerializer,
    DMFatigueWarningSerializer,
)


def _get_user_role(user):
    return getattr(user, 'role', None)


def _get_user_store_id(user):
    store = getattr(user, 'store', None)
    if store is None:
        return None
    store_id = getattr(store, 'id', None)
    if store_id is None:
        return store
    return store_id


def _success_response(data=None, message='操作成功', status_code=status.HTTP_200_OK):
    return Response({
        'code': 'success',
        'message': message,
        'data': data,
        'timestamp': timezone.now().isoformat(),
    }, status=status_code)


def _error_response(message='操作失败', data=None, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({
        'code': 'error',
        'message': message,
        'data': data,
        'timestamp': timezone.now().isoformat(),
    }, status=status_code)


class DMProfileViewSet(viewsets.ModelViewSet):
    queryset = DMProfile.objects.select_related('user', 'user__store').all()
    permission_classes = [IsAuthenticated, DMProfilePermission]
    filterset_class = DMProfileFilter
    search_fields = [
        'user__username',
        'user__name',
        'user__phone',
    ]
    ordering_fields = [
        'join_date',
        'total_sessions',
        'avg_rating',
        'consecutive_days',
        'created_at',
    ]
    ordering = ['-created_at']

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            skill_count=Count('skills', distinct=True)
        )
        role = _get_user_role(self.request.user)
        if role == UserRole.PLATFORM_ADMIN:
            return qs
        user_store_id = _get_user_store_id(self.request.user)
        if user_store_id:
            return qs.filter(user__store_id=user_store_id)
        if role == UserRole.DM:
            return qs.filter(user_id=self.request.user.id)
        return qs.none()

    def get_serializer_class(self):
        if self.action == 'list':
            return DMProfileListSerializer
        if self.action == 'retrieve':
            return DMProfileDetailSerializer
        return DMProfileSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return _success_response(
            data=DMProfileDetailSerializer(serializer.instance).data,
            message='DM档案创建成功',
            status_code=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return _success_response(data=serializer.data, message='获取成功')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return _success_response(data=serializer.data, message='获取成功')

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
        })

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return _success_response(
            data=DMProfileDetailSerializer(instance).data,
            message='更新成功'
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return _success_response(message='删除成功', status_code=status.HTTP_200_OK)

    def _calculate_consecutive_days(self, dm_profile):
        today = timezone.now().date()
        consecutive = 0
        check_date = today

        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT DATE(scheduled_date) as work_date
                    FROM schedule
                    WHERE dm_id = %s
                      AND scheduled_date <= %s
                      AND status IN ('confirmed', 'completed')
                    ORDER BY scheduled_date DESC
                    LIMIT 30
                """, [dm_profile.user_id, today])
                work_dates = [row[0] for row in cursor.fetchall()]

            while check_date >= today - timedelta(days=30):
                if check_date in work_dates:
                    consecutive += 1
                    check_date -= timedelta(days=1)
                else:
                    break
        except Exception:
            pass

        return consecutive

    def _get_workload_stats(self, dm_profile):
        today = timezone.now().date()
        first_day = today.replace(day=1)
        last_day = today.replace(day=monthrange(today.year, today.month)[1])

        current_month_sessions = 0
        current_month_total_minutes = 0

        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as session_count,
                        COALESCE(SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)), 0) as total_minutes
                    FROM schedule
                    WHERE dm_id = %s
                      AND scheduled_date BETWEEN %s AND %s
                      AND status IN ('confirmed', 'completed')
                """, [dm_profile.user_id, first_day, last_day])
                row = cursor.fetchone()
                if row:
                    current_month_sessions = row[0] or 0
                    current_month_total_minutes = row[1] or 0
        except Exception:
            pass

        consecutive_days = self._calculate_consecutive_days(dm_profile)
        fatigue_warning = consecutive_days >= 3

        dm_profile.consecutive_days = consecutive_days
        dm_profile.fatigue_warning = fatigue_warning
        dm_profile.save(update_fields=['consecutive_days', 'fatigue_warning'])

        return {
            'dm_id': dm_profile.id,
            'dm_name': dm_profile.user.name,
            'current_month_sessions': current_month_sessions,
            'current_month_total_minutes': current_month_total_minutes,
            'consecutive_days': consecutive_days,
            'fatigue_warning': fatigue_warning,
            'fatigue_level': 'critical' if consecutive_days >= 5 else (
                'warning' if consecutive_days >= 3 else (
                    'normal' if consecutive_days >= 2 else 'good'
                )
            ),
            'total_sessions': dm_profile.total_sessions,
            'avg_rating': dm_profile.avg_rating,
        }

    @action(detail=True, methods=['get'], url_path='workload')
    def workload(self, request, pk=None):
        dm_profile = self.get_object()
        stats = self._get_workload_stats(dm_profile)
        serializer = DMWorkloadStatsSerializer(stats)
        return _success_response(data=serializer.data, message='获取工作量统计成功')

    @action(detail=False, methods=['get'], url_path='workload/all')
    def workload_all(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        stats_list = []
        for dm_profile in queryset:
            stats = self._get_workload_stats(dm_profile)
            stats_list.append(stats)
        serializer = DMWorkloadStatsSerializer(stats_list, many=True)
        return _success_response(data=serializer.data, message='获取工作量统计成功')

    @action(detail=False, methods=['get'], url_path='fatigue-warnings')
    def fatigue_warnings(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        warning_list = []

        for dm_profile in queryset:
            consecutive_days = self._calculate_consecutive_days(dm_profile)
            fatigue_warning = consecutive_days >= 3

            if fatigue_warning or request.query_params.get('show_all', '').lower() == 'true':
                if consecutive_days >= 5:
                    warning_message = '连续工作{}天，已达疲劳临界点，禁止排班！'.format(consecutive_days)
                    fatigue_level = 'critical'
                elif consecutive_days >= 3:
                    warning_message = '连续工作{}天，请注意休息调整。'.format(consecutive_days)
                    fatigue_level = 'warning'
                else:
                    warning_message = '状态良好。'
                    fatigue_level = 'good'

                warning_list.append({
                    'dm_id': dm_profile.id,
                    'dm_name': dm_profile.user.name,
                    'consecutive_days': consecutive_days,
                    'fatigue_warning': fatigue_warning,
                    'fatigue_level': fatigue_level,
                    'warning_message': warning_message,
                })

        serializer = DMFatigueWarningSerializer(warning_list, many=True)
        return _success_response(data=serializer.data, message='获取疲劳预警成功')

    @action(detail=True, methods=['post'], url_path='refresh-fatigue')
    def refresh_fatigue(self, request, pk=None):
        dm_profile = self.get_object()
        consecutive_days = self._calculate_consecutive_days(dm_profile)
        fatigue_warning = consecutive_days >= 3
        return _success_response(data={
            'consecutive_days': consecutive_days,
            'fatigue_warning': fatigue_warning,
        }, message='刷新疲劳状态成功')


class DMSkillViewSet(viewsets.ModelViewSet):
    queryset = DMSkill.objects.select_related('dm__user', 'dm__user__store', 'script').all()
    permission_classes = [IsAuthenticated, DMSkillPermission]
    filterset_class = DMSkillFilter
    search_fields = [
        'dm__user__username',
        'dm__user__name',
        'script__name',
    ]
    ordering_fields = [
        'proficiency',
        'play_count',
        'last_played',
    ]
    ordering = ['-proficiency', '-play_count']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)
        if role == UserRole.PLATFORM_ADMIN:
            return qs
        user_store_id = _get_user_store_id(self.request.user)
        if user_store_id:
            return qs.filter(dm__user__store_id=user_store_id)
        if role == UserRole.DM:
            return qs.filter(dm__user_id=self.request.user.id)
        return qs.none()

    def get_serializer_class(self):
        return DMSkillSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return _success_response(
            data=DMSkillSerializer(serializer.instance).data,
            message='DM技能创建成功',
            status_code=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return _success_response(data=serializer.data, message='获取成功')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return _success_response(data=serializer.data, message='获取成功')

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
        })

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return _success_response(
            data=DMSkillSerializer(instance).data,
            message='更新成功'
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return _success_response(message='删除成功', status_code=status.HTTP_200_OK)

    def _get_current_dm_profile(self, request):
        role = _get_user_role(request.user)
        if role == UserRole.DM:
            try:
                return request.user.dm_profile
            except DMProfile.DoesNotExist:
                return None
        return None

    @action(detail=False, methods=['post'], url_path='batch-update')
    def batch_update(self, request):
        serializer = DMSkillBatchUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        skills_data = serializer.validated_data['skills']

        role = _get_user_role(request.user)
        dm_id = request.query_params.get('dm_id') or request.data.get('dm_id')

        dm_profile = None
        if dm_id:
            try:
                dm_profile = DMProfile.objects.get(id=dm_id)
            except DMProfile.DoesNotExist:
                return _error_response(message='DM档案不存在', status_code=status.HTTP_404_NOT_FOUND)
        elif role == UserRole.DM:
            dm_profile = self._get_current_dm_profile(request)
            if not dm_profile:
                return _error_response(message='当前用户没有DM档案', status_code=status.HTTP_400_BAD_REQUEST)
        else:
            return _error_response(message='请指定dm_id参数', status_code=status.HTTP_400_BAD_REQUEST)

        if role != UserRole.PLATFORM_ADMIN:
            user_store_id = _get_user_store_id(request.user)
            if dm_profile.user.store_id != user_store_id:
                return _error_response(message='只能为本门店DM设置技能', status_code=status.HTTP_403_FORBIDDEN)
            if role == UserRole.DM and dm_profile.user_id != request.user.id:
                return _error_response(message='只能设置自己的技能', status_code=status.HTTP_403_FORBIDDEN)

        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for skill_data in skills_data:
                script_id = skill_data['script_id']
                proficiency = skill_data['proficiency']

                try:
                    skill = DMSkill.objects.get(dm=dm_profile, script_id=script_id)
                    skill.proficiency = proficiency
                    skill.save(update_fields=['proficiency'])
                    updated_count += 1
                except DMSkill.DoesNotExist:
                    DMSkill.objects.create(
                        dm=dm_profile,
                        script_id=script_id,
                        proficiency=proficiency,
                    )
                    created_count += 1

        return _success_response(data={
            'created_count': created_count,
            'updated_count': updated_count,
            'total_count': created_count + updated_count,
        }, message='批量更新DM技能成功')

    @action(detail=False, methods=['post'], url_path='set-skill')
    def set_skill(self, request):
        serializer = DMSetSkillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        script_id = serializer.validated_data['script_id']
        proficiency = serializer.validated_data['proficiency']

        role = _get_user_role(request.user)
        dm_id = request.query_params.get('dm_id') or request.data.get('dm_id')

        dm_profile = None
        if dm_id:
            try:
                dm_profile = DMProfile.objects.get(id=dm_id)
            except DMProfile.DoesNotExist:
                return _error_response(message='DM档案不存在', status_code=status.HTTP_404_NOT_FOUND)
        elif role == UserRole.DM:
            dm_profile = self._get_current_dm_profile(request)
            if not dm_profile:
                return _error_response(message='当前用户没有DM档案', status_code=status.HTTP_400_BAD_REQUEST)
        else:
            return _error_response(message='请指定dm_id参数', status_code=status.HTTP_400_BAD_REQUEST)

        if role != UserRole.PLATFORM_ADMIN:
            user_store_id = _get_user_store_id(request.user)
            if dm_profile.user.store_id != user_store_id:
                return _error_response(message='只能为本门店DM设置技能', status_code=status.HTTP_403_FORBIDDEN)
            if role == UserRole.DM and dm_profile.user_id != request.user.id:
                return _error_response(message='只能设置自己的技能', status_code=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            try:
                skill = DMSkill.objects.get(dm=dm_profile, script_id=script_id)
                skill.proficiency = proficiency
                skill.save(update_fields=['proficiency'])
                message = '技能熟练度更新成功'
            except DMSkill.DoesNotExist:
                skill = DMSkill.objects.create(
                    dm=dm_profile,
                    script_id=script_id,
                    proficiency=proficiency,
                )
                message = '技能熟练度设置成功'

        return _success_response(
            data=DMSkillSerializer(skill).data,
            message=message
        )


class DMAvailabilityViewSet(viewsets.ModelViewSet):
    queryset = DMAvailability.objects.select_related('dm__user', 'dm__user__store').all()
    permission_classes = [IsAuthenticated, DMAvailabilityPermission]
    filterset_class = DMAvailabilityFilter
    search_fields = [
        'dm__user__username',
        'dm__user__name',
        'note',
    ]
    ordering_fields = [
        'day_of_week',
        'start_time',
        'specific_date',
    ]
    ordering = ['day_of_week', 'start_time']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)
        if role == UserRole.PLATFORM_ADMIN:
            return qs
        user_store_id = _get_user_store_id(self.request.user)
        if user_store_id:
            return qs.filter(dm__user__store_id=user_store_id)
        if role == UserRole.DM:
            return qs.filter(dm__user_id=self.request.user.id)
        return qs.none()

    def get_serializer_class(self):
        return DMAvailabilitySerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return _success_response(
            data=DMAvailabilitySerializer(serializer.instance).data,
            message='DM可用时间创建成功',
            status_code=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return _success_response(data=serializer.data, message='获取成功')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return _success_response(data=serializer.data, message='获取成功')

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
        })

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return _success_response(
            data=DMAvailabilitySerializer(instance).data,
            message='更新成功'
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return _success_response(message='删除成功', status_code=status.HTTP_200_OK)

    def _get_current_dm_profile(self, request):
        role = _get_user_role(request.user)
        if role == UserRole.DM:
            try:
                return request.user.dm_profile
            except DMProfile.DoesNotExist:
                return None
        return None

    @action(detail=False, methods=['post'], url_path='batch-set')
    def batch_set(self, request):
        availabilities_data = request.data.get('availabilities', [])
        if not availabilities_data:
            return _error_response(message='可用时间列表不能为空', status_code=status.HTTP_400_BAD_REQUEST)

        role = _get_user_role(request.user)
        dm_id = request.query_params.get('dm_id') or request.data.get('dm_id')

        dm_profile = None
        if dm_id:
            try:
                dm_profile = DMProfile.objects.get(id=dm_id)
            except DMProfile.DoesNotExist:
                return _error_response(message='DM档案不存在', status_code=status.HTTP_404_NOT_FOUND)
        elif role == UserRole.DM:
            dm_profile = self._get_current_dm_profile(request)
            if not dm_profile:
                return _error_response(message='当前用户没有DM档案', status_code=status.HTTP_400_BAD_REQUEST)
        else:
            return _error_response(message='请指定dm_id参数', status_code=status.HTTP_400_BAD_REQUEST)

        if role != UserRole.PLATFORM_ADMIN:
            user_store_id = _get_user_store_id(request.user)
            if dm_profile.user.store_id != user_store_id:
                return _error_response(message='只能为本门店DM设置可用时间', status_code=status.HTTP_403_FORBIDDEN)
            if role == UserRole.DM and dm_profile.user_id != request.user.id:
                return _error_response(message='只能设置自己的可用时间', status_code=status.HTTP_403_FORBIDDEN)

        replace_all = request.data.get('replace_all', False)
        created_count = 0

        with transaction.atomic():
            if replace_all:
                DMAvailability.objects.filter(dm=dm_profile).delete()

            for avail_data in availabilities_data:
                day_of_week = avail_data.get('day_of_week')
                start_time = avail_data.get('start_time')
                end_time = avail_data.get('end_time')
                is_recurring = avail_data.get('is_recurring', True)
                specific_date = avail_data.get('specific_date')
                is_unavailable = avail_data.get('is_unavailable', False)
                note = avail_data.get('note', '')

                if day_of_week is None or start_time is None or end_time is None:
                    continue
                if not is_recurring and not specific_date:
                    continue

                DMAvailability.objects.create(
                    dm=dm_profile,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    end_time=end_time,
                    is_recurring=is_recurring,
                    specific_date=specific_date,
                    is_unavailable=is_unavailable,
                    note=note,
                )
                created_count += 1

        return _success_response(data={
            'created_count': created_count,
            'replace_all': replace_all,
        }, message='批量设置可用时间成功')


class DMTemporaryUnavailableViewSet(viewsets.ModelViewSet):
    queryset = DMTemporaryUnavailable.objects.select_related('dm__user', 'dm__user__store').all()
    permission_classes = [IsAuthenticated, DMTemporaryUnavailablePermission]
    filterset_class = DMTemporaryUnavailableFilter
    search_fields = [
        'dm__user__username',
        'dm__user__name',
        'reason',
    ]
    ordering_fields = [
        'start_date',
        'end_date',
        'is_approved',
        'created_at',
    ]
    ordering = ['-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)
        if role == UserRole.PLATFORM_ADMIN:
            return qs
        user_store_id = _get_user_store_id(self.request.user)
        if user_store_id:
            return qs.filter(dm__user__store_id=user_store_id)
        if role == UserRole.DM:
            return qs.filter(dm__user_id=self.request.user.id)
        return qs.none()

    def get_serializer_class(self):
        return DMTemporaryUnavailableSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return _success_response(
            data=DMTemporaryUnavailableSerializer(serializer.instance).data,
            message='请假申请创建成功',
            status_code=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return _success_response(data=serializer.data, message='获取成功')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return _success_response(data=serializer.data, message='获取成功')

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
        })

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return _success_response(
            data=DMTemporaryUnavailableSerializer(instance).data,
            message='更新成功'
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return _success_response(message='删除成功', status_code=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        instance = self.get_object()
        serializer = DMTemporaryUnavailableApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_approved = serializer.validated_data['is_approved']

        instance.is_approved = is_approved
        instance.save(update_fields=['is_approved'])

        message = '请假已批准' if is_approved else '请假已驳回'
        return _success_response(
            data=DMTemporaryUnavailableSerializer(instance).data,
            message=message
        )

    @action(detail=False, methods=['post'], url_path='batch-approve')
    def batch_approve(self, request):
        ids = request.data.get('ids', [])
        is_approved = request.data.get('is_approved', True)

        if not ids:
            return _error_response(message='请指定要审批的记录ID列表', status_code=status.HTTP_400_BAD_REQUEST)

        role = _get_user_role(request.user)
        qs = self.get_queryset().filter(id__in=ids, is_approved=False)

        if role != UserRole.PLATFORM_ADMIN:
            user_store_id = _get_user_store_id(request.user)
            qs = qs.filter(dm__user__store_id=user_store_id)

        updated_count = qs.update(is_approved=is_approved)
        message = f'已批准{updated_count}条请假记录' if is_approved else f'已驳回{updated_count}条请假记录'
        return _success_response(data={
            'updated_count': updated_count,
            'is_approved': is_approved,
        }, message=message)
