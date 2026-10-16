<script>
  import { canManageTime as canManageTimeStore } from '../../stores/permissions.js';
  import DataTable from '../DataTable.svelte';

  let {
    bleps = [],
    currentUser,
    onEdit = () => {},
    onDelete = () => {},
    onAdd = () => {},
  } = $props();

  const canManageTime = $derived($canManageTimeStore);

  function within24h(iso) {
    if (!iso) return false;
    return Date.now() - new Date(iso).getTime() < 24 * 60 * 60 * 1000;
  }

  function isEditable(blep) {
    if (canManageTime) return true;
    if (blep.user !== currentUser?.id) return false;
    return within24h(blep.start_time);
  }

  function fmt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  }

  function elapsed(b) {
    if (!b.start_time) return '—';
    const endMs = b.end_time ? new Date(b.end_time).getTime() : Date.now();
    const s = Math.max(0, Math.floor((endMs - new Date(b.start_time).getTime()) / 1000));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }
</script>

<section>
  <h3>Work Sessions</h3>
  <DataTable
    rows={bleps}
    key={(blep) => blep.blep_id}
    emptyText="No work sessions recorded."
    columns={[
      { id: 'worker',  label: 'Worker',  cell: workerCell },
      { id: 'start',   label: 'Start',   cell: startCell },
      { id: 'end',     label: 'End',     cell: endCell },
      { id: 'elapsed', label: 'Elapsed', cell: elapsedCell },
      { id: 'actions', label: '',        cell: actionsCell },
    ]}
  />
  <p><button type="button" onclick={onAdd}>Add Entry</button></p>
</section>

{#snippet workerCell(blep)}{blep.user_name || '—'}{/snippet}
{#snippet startCell(blep)}{fmt(blep.start_time)}{/snippet}
{#snippet endCell(blep)}{blep.end_time ? fmt(blep.end_time) : 'Active'}{/snippet}
{#snippet elapsedCell(blep)}{elapsed(blep)}{/snippet}
{#snippet actionsCell(blep)}
  {#if isEditable(blep)}
    <button type="button" onclick={() => onEdit(blep)}>Edit</button>
    <button type="button" onclick={() => onDelete(blep)}>Delete</button>
  {/if}
{/snippet}
