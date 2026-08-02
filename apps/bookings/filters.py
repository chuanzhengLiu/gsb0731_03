import django_filters
from django.db.models import Q

from .models import Booking, BookingStatus


class BookingFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='date', lookup_expr='lte')
    date = django_filters.DateFilter(field_name='date')
    status = django_filters.ChoiceFilter(
        field_name='status',
        choices=BookingStatus.choices
    )
    store = django_filters.NumberFilter(field_name='store_id')
    player_count = django_filters.NumberFilter(field_name='player_count')
    player_count_gte = django_filters.NumberFilter(
        field_name='player_count',
        lookup_expr='gte'
    )
    player_count_lte = django_filters.NumberFilter(
        field_name='player_count',
        lookup_expr='lte'
    )
    customer = django_filters.CharFilter(
        method='filter_customer',
        label='客户姓名或电话'
    )

    class Meta:
        model = Booking
        fields = [
            'date', 'date_from', 'date_to',
            'status', 'store',
            'player_count', 'player_count_gte', 'player_count_lte',
            'customer'
        ]

    def filter_customer(self, queryset, name, value):
        return queryset.filter(
            Q(customer_name__icontains=value) |
            Q(customer_phone__icontains=value)
        )
