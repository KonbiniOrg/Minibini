from rest_framework import serializers
from apps.expenses.models import Expense
from apps.jobs.models import Job


class NewMaterialSerializer(serializers.Serializer):
    """Inline new-material descriptor — created atomically with the expense.
    An inventoried `inventory_item_id` routes to a stock receipt (QOH ↑);
    otherwise a consumable material is created at `price`."""
    job_id = serializers.IntegerField()
    description = serializers.CharField(required=False, allow_blank=True, default='')
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=1,
    )
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, default=None,
    )
    inventory_item_id = serializers.IntegerField(
        required=False, allow_null=True, default=None,
    )


class ExpenseSerializer(serializers.ModelSerializer):
    entered_by_name = serializers.SerializerMethodField()
    purchased_by_name = serializers.SerializerMethodField()
    task_name = serializers.SerializerMethodField()
    job_id = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    accounting_category_name = serializers.CharField(
        source='accounting_category.name', read_only=True, default=None,
    )
    reimbursement_paid_on = serializers.DateField(
        source='reimbursement.paid_on', read_only=True, default=None,
    )
    new_material = NewMaterialSerializer(required=False, write_only=True)
    job = serializers.PrimaryKeyRelatedField(
        queryset=Job.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model = Expense
        fields = [
            'id', 'entered_by', 'entered_by_name',
            'purchased_by', 'purchased_by_name',
            'amount', 'purchased_on', 'description',
            'accounting_category', 'accounting_category_name',
            'payment_method', 'payment_account_id', 'reference_number',
            'job', 'material', 'task_name', 'job_id', 'job_number', 'job_name',
            'status', 'qbo_id', 'qbo_sync_error',
            'reimbursement', 'reimbursement_paid_on',
            'created_at', 'updated_at',
            'new_material',
        ]
        read_only_fields = [
            'id', 'entered_by', 'entered_by_name', 'purchased_by_name',
            'task_name', 'job_id', 'job_number', 'job_name',
            'accounting_category_name',
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

    def _job(self, obj):
        # Job is now the direct cost anchor (no longer derived through material).
        return obj.job

    def get_task_name(self, obj):
        if not obj.material_id:
            return None
        mat = obj.material
        if mat.task_id:
            return mat.task.name
        return None

    def get_job_id(self, obj):
        job = self._job(obj)
        return job.job_id if job else None

    def get_job_number(self, obj):
        job = self._job(obj)
        return job.job_number if job else None

    def get_job_name(self, obj):
        job = self._job(obj)
        return job.name if job else None
