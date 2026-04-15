from django.contrib import admin
from .models import Expense, Reimbursement


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'pk', 'purchased_on', 'entered_by', 'purchased_by',
        'amount', 'payment_method', 'status',
    ]
    list_filter = ['status', 'payment_method']
    search_fields = ['description', 'reference_number']
    ordering = ['-purchased_on', '-created_at']


@admin.register(Reimbursement)
class ReimbursementAdmin(admin.ModelAdmin):
    list_display = [
        'pk', 'paid_on', 'purchased_by', 'status', 'reference_number',
    ]
    list_filter = ['status']
    search_fields = ['reference_number', 'notes']
    ordering = ['-paid_on']
