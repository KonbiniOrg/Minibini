<script>
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import ServiceItemManager from '../../components/ServiceItemManager.svelte';
  import { canManageJobs, canManageFinancials, canManageConfig }
    from '../../stores/permissions.js';

  let canEdit = $derived($canManageJobs || $canManageFinancials || $canManageConfig);
</script>

<div class="page-body">
<CatalogTabs />
<ServiceItemManager {canEdit} />
</div>
