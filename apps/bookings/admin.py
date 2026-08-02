from django.contrib import admin

from .models import Booking, BookingPlayer, BookingStatus, PlayerGender


class BookingPlayerInline(admin.TabularInline):
    model = BookingPlayer
    extra = 0
    min_num = 0
    fields = [
        'name', 'phone', 'gender', 'tags',
        'horror_tolerance', 'accept_reverse'
    ]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'store', 'date', 'start_time', 'duration_minutes',
        'player_count', 'status', 'customer_name', 'customer_phone',
        'deposit_amount', 'created_by', 'created_at'
    ]
    list_display_links = ['id', 'date', 'start_time']
    search_fields = ['customer_name', 'customer_phone', 'store__name']
    list_filter = [
        'store', 'status', 'date', 'created_at',
        ('created_by', admin.RelatedOnlyFieldListFilter)
    ]
    readonly_fields = ['created_at', 'updated_at']
    autocomplete_fields = ['store', 'created_by']
    inlines = [BookingPlayerInline]
    date_hierarchy = 'date'
    actions = ['confirm_bookings', 'cancel_bookings', 'complete_bookings']

    fieldsets = (
        ('基本信息', {
            'fields': ('store', 'date', 'start_time', 'duration_minutes', 'player_count')
        }),
        ('偏好设置', {
            'fields': ('preferences',),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': ('status',)
        }),
        ('客户信息', {
            'fields': ('customer_name', 'customer_phone', 'deposit_amount')
        }),
        ('系统信息', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def confirm_bookings(self, request, queryset):
        updated = 0
        for booking in queryset:
            if booking.can_transition_to(BookingStatus.CONFIRMED):
                booking.status = BookingStatus.CONFIRMED
                booking.save()
                updated += 1
        self.message_user(request, f'成功确认 {updated} 个预约')
    confirm_bookings.short_description = '批量确认预约'

    def cancel_bookings(self, request, queryset):
        updated = 0
        for booking in queryset:
            if booking.can_transition_to(BookingStatus.CANCELLED):
                booking.status = BookingStatus.CANCELLED
                booking.save()
                updated += 1
        self.message_user(request, f'成功取消 {updated} 个预约')
    cancel_bookings.short_description = '批量取消预约'

    def complete_bookings(self, request, queryset):
        updated = 0
        for booking in queryset:
            if booking.can_transition_to(BookingStatus.COMPLETED):
                booking.status = BookingStatus.COMPLETED
                booking.save()
                updated += 1
        self.message_user(request, f'成功完成 {updated} 个预约')
    complete_bookings.short_description = '批量完成预约'


@admin.register(BookingPlayer)
class BookingPlayerAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'booking', 'name', 'phone', 'gender',
        'horror_tolerance', 'accept_reverse', 'created_at'
    ]
    list_display_links = ['id', 'name']
    search_fields = ['name', 'phone', 'booking__customer_name']
    list_filter = [
        'gender', 'accept_reverse', 'horror_tolerance',
        'created_at',
        ('booking__store', admin.RelatedOnlyFieldListFilter)
    ]
    readonly_fields = ['created_at']
    autocomplete_fields = ['booking']

    def get_store(self, obj):
        return obj.booking.store if obj.booking else None
    get_store.short_description = '门店'
    get_store.admin_order_field = 'booking__store'
