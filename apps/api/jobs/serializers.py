from rest_framework import serializers
from apps.jobs.models import Job
from apps.api.mixins import JobScopedCanManageMixin


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


class JobSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'self'
    contact_name = serializers.SerializerMethodField()
    project_manager_name = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()
    materials = serializers.SerializerMethodField()
    latest_change_request = serializers.SerializerMethodField()
    has_estimates = serializers.SerializerMethodField()
    has_accepted_estimate = serializers.SerializerMethodField()
    estimated_amount = serializers.SerializerMethodField()
    spent_amount = serializers.SerializerMethodField()
    invoiced_amount = serializers.SerializerMethodField()
    profit_amount = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'job_id', 'job_number', 'name', 'status',
            'on_hold', 'hold_reason',
            'contact', 'contact_name', 'project_manager', 'project_manager_name',
            'can_manage',
            'customer_po_number', 'description',
            'created_date', 'start_date', 'due_date', 'completed_date',
            'tasks', 'materials', 'latest_change_request',
            'has_estimates', 'has_accepted_estimate',
            'estimated_amount', 'spent_amount', 'invoiced_amount', 'profit_amount',
        ]
        # on_hold/hold_reason are read-only — writes go through the hold/
        # release actions so the service guards always run.
        read_only_fields = ['job_id', 'job_number', 'created_date', 'completed_date',
                            'on_hold', 'hold_reason']

    def get_contact_name(self, obj):
        return f"{obj.contact.first_name} {obj.contact.last_name}"

    def get_has_estimates(self, obj):
        """Whether ANY estimate exists on this job (dead ones count). The
        header's status pill offers direct Approved only when False — a job
        with estimates is approved via estimate acceptance. Skipped in list
        context (per-row exists() would be an N+1); detail-only, like
        ``latest_change_request``."""
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return None
        return obj.estimate_set.exists()

    def get_has_accepted_estimate(self, obj):
        """Whether the job has an ACCEPTED estimate — distinct from
        ``has_estimates`` (any estimate, any status). Drives the header
        pill's approved -> in_progress option (`JobHeader.svelte`): the
        backend only refuses a manual release when an accepted estimate
        exists (JobService.update_job) — a job that never went through
        acceptance (hand-approved directly, or carrying only a draft/dead
        estimate) has no checklist to auto-release it, so manual release
        stays legal and the pill must offer it. Detail-only, same
        list-context skip as ``has_estimates`` (per-row exists() would be
        an N+1)."""
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return None
        from apps.estimates.models import Estimate
        return obj.estimate_set.filter(status=Estimate.STATUS_ACCEPTED).exists()

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

    def get_project_manager_name(self, obj):
        pm = obj.project_manager
        if pm is None:
            return None
        return pm.get_full_name() or pm.username

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

    def _invoice_claims(self, obj):
        """Build the per-job invoice claim map once, memoized. Skipped in list context.

        Returns {} in list context (mirrors the _financials/latest_change_request
        list-skip pattern) so atom serializers safely receive an empty map.
        """
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return {}
        cache = getattr(self, '_claims_cache', None)
        if cache is None:
            cache = {}
            self._claims_cache = cache
        if obj.pk not in cache:
            from apps.invoicing.claims import InvoiceClaimService
            cache[obj.pk] = InvoiceClaimService.claims_for_job(obj)
        return cache[obj.pk]

    def _estimate_claims(self, obj):
        """Build the per-job estimate claim set once, memoized. Skipped in list context.

        Returns frozenset() in list context so atom serializers receive an empty
        set and all atoms serialize as claimed=False (no N+1 per list row).
        """
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return frozenset()
        cache = getattr(self, '_est_claims_cache', None)
        if cache is None:
            cache = {}
            self._est_claims_cache = cache
        if obj.pk not in cache:
            from apps.estimates.claims import EstimateClaimService
            cache[obj.pk] = EstimateClaimService.claimed_set_for_job(obj)
        return cache[obj.pk]

    def _atom_context(self, obj):
        """Shared context dict injected into atom serializers (Task/Material)."""
        return {
            **self.context,
            'invoice_claims': self._invoice_claims(obj),
            'estimate_claims': self._estimate_claims(obj),
        }

    def get_tasks(self, obj):
        from apps.api.tasks.serializers import TaskSerializer
        # Use .all() so prefetch_related cache is hit when configured.
        # The viewset prefetches tasks already ordered by sort_order.
        tasks = obj.tasks.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'tasks' not in obj._prefetched_objects_cache:
            tasks = tasks.order_by('sort_order')
        return TaskSerializer(tasks, many=True, context=self._atom_context(obj)).data

    def get_materials(self, obj):
        from apps.api.inventory.serializers import MaterialSerializer
        materials = obj.materials.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'materials' not in obj._prefetched_objects_cache:
            materials = materials.order_by('pk')
        return MaterialSerializer(materials, many=True, context=self._atom_context(obj)).data
