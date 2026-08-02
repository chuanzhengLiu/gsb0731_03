from django.db.models import Case, When, IntegerField
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .models import Script, Role, ScriptStatus
from .serializers import (
    ScriptSerializer,
    ScriptCreateSerializer,
    ScriptListSerializer,
    ScriptDetailSerializer,
    RoleSerializer,
    RoleCreateSerializer,
    ScriptRecommendationQuerySerializer,
)
from .permissions import ScriptPermission, RolePermission
from .filters import ScriptFilter


class ScriptViewSet(viewsets.ModelViewSet):
    queryset = Script.objects.select_related('store').prefetch_related('roles').all()
    filterset_class = ScriptFilter
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'duration_minutes', 'difficulty']
    ordering = ['-created_at']

    def get_permissions(self):
        return [IsAuthenticated(), ScriptPermission()]

    def get_serializer_class(self):
        if self.action == 'list':
            return ScriptListSerializer
        elif self.action == 'retrieve':
            return ScriptDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ScriptCreateSerializer
        return ScriptSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        if hasattr(user, 'store') and user.store is not None:
            if self.action in ['list', 'retrieve']:
                store_qs = qs.filter(store_id=user.store_id)
                public_qs = qs.filter(status=ScriptStatus.AVAILABLE)
                return (store_qs | public_qs).distinct()
            return qs.filter(store_id=user.store_id)
        return qs.filter(status=ScriptStatus.AVAILABLE)

    def perform_create(self, serializer):
        user = self.request.user
        if not (user.is_staff or user.is_superuser):
            if hasattr(user, 'store') and user.store is not None:
                serializer.save(store_id=user.store_id)
                return
        serializer.save()

    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        script = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(ScriptStatus.choices):
            return Response(
                {'detail': '无效的状态值'},
                status=status.HTTP_400_BAD_REQUEST
            )
        script.status = new_status
        script.save()
        serializer = ScriptDetailSerializer(script)
        return Response(serializer.data)


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.select_related('script').all()
    search_fields = ['name', 'description']
    ordering_fields = ['id']
    ordering = ['id']

    def get_permissions(self):
        return [IsAuthenticated(), RolePermission()]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RoleCreateSerializer
        return RoleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        script_id = self.request.query_params.get('script')
        if script_id:
            qs = qs.filter(script_id=script_id)
        return qs


class ScriptRecommendationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = ScriptRecommendationQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        player_count = query_serializer.validated_data['player_count']
        preferred_types = query_serializer.validated_data.get('preferred_types', [])

        queryset = Script.objects.filter(
            status=ScriptStatus.AVAILABLE,
            inventory__gt=0,
            **{f'player_count__total': player_count}
        ).select_related('store')

        user = request.user
        if not (user.is_staff or user.is_superuser):
            if hasattr(user, 'store') and user.store is not None:
                store_qs = queryset.filter(store_id=user.store_id)
                public_qs = queryset
                queryset = (store_qs | public_qs).distinct()

        if preferred_types:
            type_order = []
            for idx, ptype in enumerate(preferred_types):
                type_order.append(When(type=ptype, then=idx))
            queryset = queryset.annotate(
                type_priority=Case(
                    *type_order,
                    default=len(preferred_types),
                    output_field=IntegerField()
                )
            ).order_by('type_priority', '-created_at')
        else:
            queryset = queryset.order_by('-created_at')

        serializer = ScriptListSerializer(queryset[:20], many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })
