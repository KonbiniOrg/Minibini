<script>
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import ServiceItemManager from '../../components/ServiceItemManager.svelte';
  import ServiceItemsImportPanel from '../../components/qboimport/ServiceItemsImportPanel.svelte';
  import QboPullButton from '../../components/qboimport/QboPullButton.svelte';
  import { canManageJobs, canManageFinancials, canManageConfig }
    from '../../stores/permissions.js';

  let canEdit = $derived($canManageJobs || $canManageFinancials || $canManageConfig);
  let pullEpoch = $state(0);
  let refreshEpoch = $state(0);
</script>

<div class="page-body">
<CatalogTabs />

{#if $canManageFinancials || $canManageConfig}
  <QboPullButton area="services" onPulled={() => pullEpoch++} />
  {#key pullEpoch}
    <ServiceItemsImportPanel onCommitted={() => refreshEpoch++} />
  {/key}
{/if}

{#key refreshEpoch}
  <ServiceItemManager {canEdit} />
{/key}
</div>
