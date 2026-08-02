from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import UserRole

from .models import PlayerProfile, RoleAssignment
from .serializers import (
    PlayerProfileSerializer,
    PlayerProfileListSerializer,
    PlayerProfileDetailSerializer,
    PlayerPreferenceSubmissionSerializer,
    RoleAssignmentSerializer,
    RoleAssignmentBatchCreateSerializer,
    RoleMatchRequestSerializer,
    RoleMatchResultSerializer,
    SatisfactionUpdateSerializer,
)
from .permissions import (
    PlayerProfilePermission,
    RoleAssignmentPermission,
    RoleMatchPermission,
    PlayerHistoryPermission,
    _get_user_role,
    _get_user_store_id,
    _get_user_phone,
)
from .filters import PlayerProfileFilter, RoleAssignmentFilter

logger = logging.getLogger(__name__)


PLATFORM_ADMIN = UserRole.PLATFORM_ADMIN
STORE_MANAGER = UserRole.STORE_MANAGER
ASSISTANT_MANAGER = UserRole.ASSISTANT_MANAGER
DM = UserRole.DM
FRONT_DESK = UserRole.FRONT_DESK
PLAYER = UserRole.PLAYER


class PlayerProfileViewSet(viewsets.ModelViewSet):
    queryset = PlayerProfile.objects.all()
    permission_classes = [PlayerProfilePermission]
    filterset_class = PlayerProfileFilter
    search_fields = ['phone', 'name']
    ordering_fields = ['created_at', 'updated_at']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)

        if role == PLATFORM_ADMIN:
            return qs

        if role == PLAYER:
            user_phone = _get_user_phone(self.request.user)
            if user_phone:
                return qs.filter(phone=user_phone)
            return qs.none()

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return PlayerProfileListSerializer
        if self.action == 'retrieve':
            return PlayerProfileDetailSerializer
        if self.action == 'submit_preference':
            return PlayerPreferenceSubmissionSerializer
        return PlayerProfileSerializer

    @action(detail=False, methods=['get'], url_path='lookup-by-phone')
    def lookup_by_phone(self, request):
        phone = request.query_params.get('phone')
        if not phone:
            return Response(
                {'detail': '请提供phone参数'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            profile = PlayerProfile.objects.get(phone=phone)
            self.check_object_permissions(request, profile)
            serializer = PlayerProfileDetailSerializer(profile)
            return Response(serializer.data)
        except PlayerProfile.DoesNotExist:
            return Response(
                {'detail': '未找到该手机号对应的玩家档案', 'found': False},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=['post'], url_path='submit-preference')
    def submit_preference(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = serializer.save()
        output_serializer = PlayerProfileDetailSerializer(profile)
        return Response(output_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        profile = self.get_object()
        self.check_object_permissions(request, profile)

        history_roles = profile.history_roles or []
        history_roles_sorted = sorted(
            history_roles,
            key=lambda x: x.get('date', ''),
            reverse=True,
        )

        response_data = {
            'player_profile_id': profile.id,
            'player_name': profile.name,
            'player_phone': profile.phone,
            'total_plays': profile.total_plays,
            'avg_satisfaction': profile.avg_satisfaction,
            'history_roles': history_roles_sorted,
        }

        return Response(response_data)


class RoleAssignmentViewSet(viewsets.ModelViewSet):
    queryset = RoleAssignment.objects.select_related(
        'schedule', 'player_profile', 'role', 'role__script'
    ).all()
    permission_classes = [RoleAssignmentPermission]
    filterset_class = RoleAssignmentFilter
    search_fields = ['player_name', 'player_phone']
    ordering_fields = ['assigned_at', 'created_at', 'match_score']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)

        if role == PLATFORM_ADMIN:
            return qs

        user_store_id = _get_user_store_id(self.request.user)
        if not user_store_id:
            return qs.none()

        try:
            from django.apps import apps
            from django.db.models import Q

            Room = apps.get_model('stores', 'Room')
            room_ids = list(Room.objects.filter(
                store_id=user_store_id
            ).values_list('id', flat=True))

            try:
                Schedule = apps.get_model('scheduling', 'Schedule')
                schedule_ids = list(Schedule.objects.filter(
                    room_id__in=room_ids
                ).values_list('id', flat=True))

                store_assignments = qs.filter(schedule_id__in=schedule_ids)
            except LookupError:
                store_assignments = qs.none()

        except LookupError:
            store_assignments = qs.none()

        if role == DM:
            try:
                from django.apps import apps
                from apps.accounts.models import DMProfile

                dm_user_id = self.request.user.id
                dm_profile = DMProfile.objects.filter(
                    user_id=dm_user_id
                ).first()
                if dm_profile:
                    try:
                        Schedule = apps.get_model('scheduling', 'Schedule')
                        dm_schedule_ids = list(Schedule.objects.filter(
                            dm_id=dm_profile.id
                        ).values_list('id', flat=True))
                        dm_assignments = qs.filter(
                            schedule_id__in=dm_schedule_ids
                        )
                        qs = store_assignments | dm_assignments
                        qs = qs.distinct()
                        return qs
                    except LookupError:
                        pass
            except LookupError:
                pass

        return store_assignments

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RoleAssignmentSerializer
        if self.action == 'batch_create':
            return RoleAssignmentBatchCreateSerializer
        if self.action == 'update_satisfaction':
            return SatisfactionUpdateSerializer
        return RoleAssignmentSerializer

    def perform_destroy(self, instance):
        super().perform_destroy(instance)

    @action(detail=False, methods=['post'], url_path='batch-create')
    def batch_create(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            created = serializer.save()
        except Exception as e:
            logger.error(f'批量创建角色分配失败: {e}', exc_info=True)
            return Response(
                {'detail': f'批量创建失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        output_serializer = RoleAssignmentSerializer(created, many=True)
        return Response(
            {
                'created_count': len(created),
                'assignments': output_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post', 'patch'], url_path='update-satisfaction')
    def update_satisfaction(self, request, pk=None):
        instance = self.get_object()
        self.check_object_permissions(request, instance)

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
        )
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = serializer.save()
        output_serializer = RoleAssignmentSerializer(updated)
        return Response(output_serializer.data)


class RoleMatchView(APIView):
    permission_classes = [RoleMatchPermission]

    def post(self, request):
        serializer = RoleMatchRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = _get_user_role(request.user)
        user_store_id = _get_user_store_id(request.user)

        if role != PLATFORM_ADMIN:
            schedule_id = serializer.validated_data.get('schedule_id')
            try:
                from apps.scheduling.models import Schedule
                from apps.stores.models import Room

                schedule = Schedule.objects.select_related('room').get(
                    id=schedule_id
                )
                schedule_store_id = None
                if schedule.room_id:
                    try:
                        room = Room.objects.get(id=schedule.room_id)
                        schedule_store_id = room.store_id
                    except Room.DoesNotExist:
                        pass

                if schedule_store_id and schedule_store_id != user_store_id:
                    return Response(
                        {'detail': '无权操作其他门店的场次'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except Exception as e:
                logger.warning(f'检查门店权限时出错: {e}')

        try:
            result, schedule, script, match_roles = serializer.execute_match()
        except Exception as e:
            logger.error(f'执行角色匹配算法失败: {e}', exc_info=True)
            return Response(
                {'detail': f'匹配算法执行失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        result_dict = result.to_dict()

        result_dict['schedule_id'] = schedule.id
        result_dict['script_id'] = script.id
        result_dict['script_name'] = script.name
        result_dict['script_type'] = script.type
        result_dict['script_type_display'] = script.get_type_display()

        result_dict['available_roles'] = [
            {
                'role_id': r.role_id,
                'role_name': r.role_name,
                'suggested_gender': r.suggested_gender,
                'personality_tags': r.personality_tags,
            }
            for r in match_roles
        ]

        return Response(result_dict, status=status.HTTP_200_OK)


class PlayerHistoryView(APIView):
    permission_classes = [PlayerHistoryPermission]

    def get(self, request, pk=None):
        try:
            profile = PlayerProfile.objects.get(id=pk)
        except PlayerProfile.DoesNotExist:
            return Response(
                {'detail': '玩家档案不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        self.check_object_permissions(request, profile)

        role = _get_user_role(request.user)
        if role == PLAYER:
            user_phone = _get_user_phone(request.user)
            if user_phone and profile.phone and user_phone != profile.phone:
                return Response(
                    {'detail': '无权查看其他玩家的历史记录'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            elif not (user_phone and profile.phone):
                return Response(
                    {'detail': '无权查看该玩家的历史记录'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        history_roles = profile.history_roles or []
        history_roles_sorted = sorted(
            history_roles,
            key=lambda x: x.get('date', ''),
            reverse=True,
        )

        script_ids = [r.get('script_id') for r in history_roles_sorted if r.get('script_id')]
        script_info_map = {}
        if script_ids:
            try:
                from apps.scripts.models import Script
                scripts = Script.objects.filter(id__in=script_ids)
                for s in scripts:
                    script_info_map[s.id] = {
                        'script_id': s.id,
                        'script_name': s.name,
                        'script_type': s.type,
                        'script_type_display': s.get_type_display(),
                    }
            except LookupError:
                pass

        enriched_history = []
        for hr in history_roles_sorted:
            item = dict(hr)
            script_id = hr.get('script_id')
            if script_id and script_id in script_info_map:
                item.update(script_info_map[script_id])
            enriched_history.append(item)

        response_data = {
            'player_profile_id': profile.id,
            'player_name': profile.name,
            'player_phone': profile.phone,
            'preference_tags': profile.preference_tags,
            'horror_tolerance': profile.horror_tolerance,
            'accept_reverse': profile.accept_reverse,
            'total_plays': profile.total_plays,
            'last_visit_date': profile.last_visit_date,
            'avg_satisfaction': profile.avg_satisfaction,
            'history_count': len(enriched_history),
            'history_roles': enriched_history,
        }

        return Response(response_data)
