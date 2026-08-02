from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'user-manage', views.UserViewSet, basename='user-manage')

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('reset-password/', views.PasswordResetView.as_view(), name='reset_password'),
    path('me/', views.MeView.as_view(), name='me'),
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('', include(router.urls)),
]
