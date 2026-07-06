from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='auth-login'),
    path('logout/', views.logout_view, name='auth-logout'),
    path('me/', views.me_view, name='auth-me'),
    path('me/password/', views.change_password_view, name='auth-password-change'),
    path('me/schedule-envelope/', views.me_schedule_envelope_view,
         name='auth-me-schedule-envelope'),
    path('users/', views.users_list, name='auth-users'),
    path('refresh/', views.refresh_stub, name='auth-refresh'),
]
