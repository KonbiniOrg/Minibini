from django.urls import path
from .views import clock_in, clock_out, shift_report

urlpatterns = [
    path('clock-in/', clock_in, name='shift-clock-in'),
    path('clock-out/', clock_out, name='shift-clock-out'),
    path('report/', shift_report, name='shift-report'),
]
