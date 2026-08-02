from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/stores/', include('apps.stores.urls')),
    path('api/scripts/', include('apps.scripts.urls')),
    path('api/dms/', include('apps.dms.urls')),
    path('api/bookings/', include('apps.bookings.urls')),
    path('api/scheduling/', include('apps.scheduling.urls')),
    path('api/players/', include('apps.players.urls')),
    path('api/reviews/', include('apps.reviews.urls')),
    path('api/audit/', include('apps.audit.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
