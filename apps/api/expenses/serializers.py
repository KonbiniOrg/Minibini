from rest_framework import serializers
from apps.expenses.models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    entered_by_name = serializers.SerializerMethodField()
    purchased_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            'id', 'entered_by', 'entered_by_name',
            'purchased_by', 'purchased_by_name',
            'amount', 'purchased_on', 'description',
            'accounting_category',
            'payment_method', 'payment_account_id', 'reference_number',
            'material',
            'status', 'qbo_id', 'qbo_sync_error',
            'reimbursement',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'entered_by', 'entered_by_name', 'purchased_by_name',
            'status', 'qbo_id', 'qbo_sync_error', 'reimbursement',
            'created_at', 'updated_at',
        ]
        extra_kwargs = {
            'purchased_by': {'required': False, 'allow_null': True},
            'payment_account_id': {'required': False, 'allow_blank': True},
            'reference_number': {'required': False, 'allow_blank': True},
            'description': {'required': False, 'allow_blank': True},
            'material': {'required': False, 'allow_null': True},
        }

    def _name(self, user):
        if not user:
            return None
        return user.get_full_name() or user.username

    def get_entered_by_name(self, obj):
        return self._name(obj.entered_by)

    def get_purchased_by_name(self, obj):
        return self._name(obj.purchased_by)
