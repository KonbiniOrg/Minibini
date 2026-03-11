from django.urls import path
from apps.api.stubs import stub_501

urlpatterns = [
    path('', stub_501('POST /api/expenses/'), name='expense-list'),
]
