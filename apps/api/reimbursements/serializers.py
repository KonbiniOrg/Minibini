from rest_framework import serializers
from apps.expenses.models import Reimbursement


class ReimbursementSerializer(serializers.ModelSerializer):
    purchased_by_name = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    expense_count = serializers.SerializerMethodField()

    class Meta:
        model = Reimbursement
        fields = [
            'id', 'purchased_by', 'purchased_by_name',
            'paid_on', 'payment_account_id', 'reference_number', 'notes',
            'created_by', 'status',
            'qbo_id', 'qbo_sync_error',
            'created_at', 'total', 'expense_count',
        ]
        read_only_fields = [
            'id', 'purchased_by_name', 'created_by', 'status',
            'qbo_id', 'qbo_sync_error', 'created_at', 'total', 'expense_count',
        ]

    def get_purchased_by_name(self, obj):
        u = obj.purchased_by
        return u.get_full_name() or u.username

    def get_total(self, obj):
        return str(obj.total)

    def get_expense_count(self, obj):
        return obj.expenses.count()


class _LazyUserPKField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        from django.contrib.auth import get_user_model
        return get_user_model().objects.all()


class ReimbursementCreateSerializer(serializers.Serializer):
    purchased_by = _LazyUserPKField()
    expense_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
    )
    paid_on = serializers.DateField()
    payment_account_id = serializers.CharField(max_length=50)
    reference_number = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default='',
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, default='',
    )
