from django.contrib import admin
from .models import User, Configuration, AccountingCategory


@admin.register(AccountingCategory)
class AccountingCategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'taxable', 'is_active', 'qbo_item_id', 'qbo_expense_account_id']
    list_filter = ['taxable', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['name']
