import django_filters

from .models import Store, Room


class StoreFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')

    class Meta:
        model = Store
        fields = ['name']


class RoomFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    store = django_filters.NumberFilter(field_name='store_id')
    is_active = django_filters.BooleanFilter(field_name='is_active')
    has_props = django_filters.BooleanFilter(field_name='has_props')

    class Meta:
        model = Room
        fields = ['name', 'store', 'is_active', 'has_props']
