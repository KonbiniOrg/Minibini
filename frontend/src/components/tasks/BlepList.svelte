<script>
  let {
    bleps = [],
    currentUser,
    userPermissions = [],
    onEdit = () => {},
    onDelete = () => {},
    onAdd = () => {},
  } = $props();

  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

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
  {#if bleps.length === 0}
    <p>No work sessions recorded.</p>
  {:else}
    <table class="data-table">
      <thead>
        <tr>
          <th>Worker</th><th>Start</th><th>End</th><th>Elapsed</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each bleps as blep (blep.blep_id)}
          <tr>
            <td>{blep.user_name || '—'}</td>
            <td>{fmt(blep.start_time)}</td>
            <td>{blep.end_time ? fmt(blep.end_time) : 'Active'}</td>
            <td>{elapsed(blep)}</td>
            <td>
              {#if isEditable(blep)}
                <button type="button" onclick={() => onEdit(blep)}>Edit</button>
                <button type="button" onclick={() => onDelete(blep)}>Delete</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  <p><button type="button" onclick={onAdd}>Add Entry</button></p>
</section>
