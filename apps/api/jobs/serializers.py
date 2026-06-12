from rest_framework import serializers
from apps.jobs.models import Job


class JobSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ['job_id', 'job_number', 'name', 'status']


class JobSearchSerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()

    def get_contact_name(self, obj):
        return obj.contact.name if obj.contact else None

    class Meta:
        model = Job
        fields = ['job_id', 'job_number', 'name', 'status', 'created_date', 'start_date',
                  'description', 'customer_po_number', 'contact_name']


class JobSerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()
    materials = serializers.SerializerMethodField()
    latest_change_request = serializers.SerializerMethodField()
    estimated_amount = serializers.SerializerMethodField()
    spent_amount = serializers.SerializerMethodField()
    invoiced_amount = serializers.SerializerMethodField()
    profit_amount = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'job_id', 'job_number', 'name', 'status',
            'contact', 'contact_name', 'customer_po_number', 'description',
            'created_date', 'start_date', 'due_date', 'completed_date',
            'tasks', 'materials', 'latest_change_request',
            'estimated_amount', 'spent_amount', 'invoiced_amount', 'profit_amount',
        ]
        read_only_fields = ['job_id', 'job_number', 'created_date', 'completed_date']

    def get_contact_name(self, obj):
        return f"{obj.contact.first_name} {obj.contact.last_name}"

    def _financials(self, obj):
        """Detail-only job financial rollups, computed once and memoized.

        Skipped in list context — like ``latest_change_request``, computing these
        per row would be an N+1. Returns ``None`` in list context.
        """
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return None
        cache = getattr(self, '_financials_cache', None)
        if cache is None:
            cache = {}
            self._financials_cache = cache
        if obj.pk not in cache:
            from apps.jobs.financials import compute_job_financials
            cache[obj.pk] = compute_job_financials(obj)
        return cache[obj.pk]

    def _amount(self, obj, key):
        fin = self._financials(obj)
        return None if fin is None else str(fin[key])

    def get_estimated_amount(self, obj):
        return self._amount(obj, 'estimated')

    def get_spent_amount(self, obj):
        return self._amount(obj, 'spent')

    def get_invoiced_amount(self, obj):
        return self._amount(obj, 'invoiced')

    def get_profit_amount(self, obj):
        return self._amount(obj, 'profit')

    def get_latest_change_request(self, obj):
        """Most recent customer 'Request changes' comment across the job's
        estimates, so the SPA can banner it over the auto-staged revision draft.
        Returns ``None`` when none exists. Skipped in list context — it's a
        detail-only banner, and computing it per row would be an N+1."""
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return None
        from apps.core.models import JobHistory
        est_ids = list(obj.estimate_set.values_list('estimate_id', flat=True))
        if not est_ids:
            return None
        entry = (JobHistory.objects
                 .filter(entry_type='action', object_type='estimate',
                         object_id__in=est_ids,
                         changes___action='Changes requested via customer link')
                 .order_by('-timestamp', '-pk')
                 .first())
        if entry is None:
            return None
        return {'text': entry.text, 'timestamp': entry.timestamp.isoformat()}

    def get_tasks(self, obj):
        from apps.api.tasks.serializers import TaskSerializer
        # Use .all() so prefetch_related cache is hit when configured.
        # The viewset prefetches tasks already ordered by sort_order.
        tasks = obj.tasks.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'tasks' not in obj._prefetched_objects_cache:
            tasks = tasks.order_by('sort_order')
        return TaskSerializer(tasks, many=True).data

    def get_materials(self, obj):
        from apps.api.inventory.serializers import MaterialSerializer
        materials = obj.materials.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'materials' not in obj._prefetched_objects_cache:
            materials = materials.order_by('pk')
        return MaterialSerializer(materials, many=True).data
