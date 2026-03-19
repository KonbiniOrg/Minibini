from django.urls import path
from apps.api.stubs import stub_501

urlpatterns = [
    path('clock-in/', stub_501('POST /api/shifts/clock-in/'), name='shift-clock-in'),
    path('clock-out/', stub_501('POST /api/shifts/clock-out/'), name='shift-clock-out'),
]
