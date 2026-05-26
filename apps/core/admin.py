from django.contrib import admin
from .models import User, Configuration, AccountingCategory, ScheduledProcessRun


@admin.register(AccountingCategory)
class AccountingCategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'taxable', 'is_active', 'qbo_item_id', 'qbo_expense_account_id']
    list_filter = ['taxable', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['name']


@admin.register(ScheduledProcessRun)
class ScheduledProcessRunAdmin(admin.ModelAdmin):
    list_display = ['process_name', 'started_at', 'finished_at', 'outcome']
    list_filter = ['process_name', 'outcome']
    readonly_fields = ['process_name', 'started_at', 'finished_at', 'outcome', 'summary', 'error']
    ordering = ['-started_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
