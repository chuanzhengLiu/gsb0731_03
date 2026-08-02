from django.conf import settings
from rest_framework import serializers

from .models import Store, Room


class StoreSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.get_full_name', read_only=True)
    room_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Store
        fields = ['id', 'name', 'address', 'admin', 'admin_name', 'room_count', 'created_at']
        read_only_fields = ['id', 'created_at']


class StoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ['id', 'name', 'address', 'admin', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_name(self, value):
        if Store.objects.filter(name=value).exists():
            raise serializers.ValidationError('门店名称已存在')
        return value


class StoreListSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.get_full_name', read_only=True)
    room_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Store
        fields = ['id', 'name', 'address', 'admin_name', 'room_count', 'created_at']


class RoomSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)

    class Meta:
        model = Room
        fields = [
            'id', 'store', 'store_name', 'name', 'capacity',
            'has_props', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class RoomCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ['id', 'store', 'name', 'capacity', 'has_props', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        store = attrs.get('store')
        name = attrs.get('name')
        qs = Room.objects.filter(store=store, name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({'name': '该门店下已存在相同名称的房间'})
        return attrs
