from django.db.models import Count
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Store, Room
from .serializers import (
    StoreSerializer,
    StoreCreateSerializer,
    StoreListSerializer,
    RoomSerializer,
    RoomCreateSerializer,
)
from .permissions import (
    StorePermission,
    RoomPermission,
    PLATFORM_ADMIN,
)
from .filters import StoreFilter, RoomFilter


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


class StoreViewSet(viewsets.ModelViewSet):
    queryset = Store.objects.all()
    permission_classes = [StorePermission]
    filterset_class = StoreFilter
    search_fields = ['name', 'address']
    ordering_fields = ['name', 'created_at']

    def get_queryset(self):
        qs = super().get_queryset().annotate(room_count=Count('rooms'))
        role = _get_user_role(self.request.user)
        if role == PLATFORM_ADMIN:
            return qs
        user_store_id = _get_user_store_id(self.request.user)
        if user_store_id:
            return qs.filter(id=user_store_id)
        return qs.none()

    def get_serializer_class(self):
        if self.action == 'list':
            return StoreListSerializer
        if self.action in ['create']:
            return StoreCreateSerializer
        return StoreSerializer

    @action(detail=True, methods=['get'])
    def rooms(self, request, pk=None):
        store = self.get_object()
        rooms = store.rooms.all()
        page = self.paginate_queryset(rooms)
        if page is not None:
            serializer = RoomSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = RoomSerializer(rooms, many=True)
        return Response(serializer.data)


class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.select_related('store').all()
    permission_classes = [RoomPermission]
    filterset_class = RoomFilter
    search_fields = ['name']
    ordering_fields = ['name', 'capacity', 'created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        role = _get_user_role(self.request.user)
        if role == PLATFORM_ADMIN:
            return qs
        user_store_id = _get_user_store_id(self.request.user)
        if user_store_id:
            return qs.filter(store_id=user_store_id)
        return qs.none()

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RoomCreateSerializer
        return RoomSerializer
