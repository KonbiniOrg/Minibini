from django.contrib import admin
from .models import User, Configuration, LineItemType


@admin.register(LineItemType)
class LineItemTypeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'taxable', 'is_active']
    list_filter = ['taxable', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['name']
