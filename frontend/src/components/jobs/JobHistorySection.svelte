<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let { job, onJobChange = () => {} } = $props();
  const jobId = $derived(job?.job_id);

  let history = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let noteText = $state('');
  let saving = $state(false);
  let noteError = $state('');
  let noteFields = $state({});

  // The history feed is paginated; this is a deep-dive page, so pull every
  // page (page_size=100, then follow the count) rather than just the first.
  async function fetchAllHistory(id) {
    const pageSize = 100;
    const first = await api.get(`/api/jobs/${id}/history/?page_size=${pageSize}`);
    const results = [...(first.results || [])];
    const count = first.count ?? results.length;
    const pages = Math.ceil(count / pageSize);
    for (let p = 2; p <= pages; p++) {
      const data = await api.get(`/api/jobs/${id}/history/?page=${p}&page_size=${pageSize}`);
      results.push(...(data.results || []));
    }
    return { results, count };
  }

  async function load() {
    loading = true;
    loadError = null;
    try {
      history = await fetchAllHistory(jobId);
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (jobId) load();
  });

  let entries = $derived((history?.results || []).map(h => ({ ...h, when: new Date(h.timestamp) })));

  let activeTab = $state('timeline'); // 'timeline' | 'summary'

  // --- Summary tab: roll the same events up per object ---
  function dateStr(d) {
    return d ? d.toLocaleDateString() : '';
  }
  // "created DATE, <verb> DATE, ..." for the milestones present on an object.
  function milestones(created, statusDates, specs) {
    const parts = [];
    if (created) parts.push(`created ${dateStr(created)}`);
    for (const [status, verb] of specs) {
      if (statusDates[status]) parts.push(`${verb} ${dateStr(statusDates[status])}`);
    }
    return parts.join(', ');
  }
  // ", assigned to X, N est, M h spent" from the task's live detail.
  function taskExtra(d) {
    if (!d) return '';
    const parts = [];
    if (d.assignee_name) parts.push(`assigned to ${d.assignee_name}`);
    if (d.est_worker_time != null) parts.push(`${d.est_worker_time} est`);
    if (d.actual_hours != null) parts.push(`${d.actual_hours}h spent`);
    return parts.length ? ', ' + parts.join(', ') : '';
  }

  let summary = $derived.by(() => {
    const objs = new Map();
    for (const e of entries) {
      const key = `${e.object_type}:${e.object_id}`;
      let o = objs.get(key);
      if (!o) {
        o = { type: e.object_type, id: e.object_id, label: e.source_label || e.object_type,
              link: e.source_link, created: null, edits: 0, statusDates: {} };
        objs.set(key, o);
      }
      const c = e.changes || {};
      const stat = c.status?.new ?? c.consumption_state?.new;
      if (c._created) o.created = e.when;
      else if (stat) o.statusDates[stat] = e.when;        // status move (action or audit)
      else if (Object.keys(c).some(k => !k.startsWith('_'))) o.edits += 1;  // field edit
    }
    const all = [...objs.values()];
    const byType = (t) => all.filter(o => o.type === t);
    const byCreated = (a, b) => (a.created?.getTime() || 0) - (b.created?.getTime() || 0);
    const taskDetail = new Map((job?.tasks || []).map(t => [t.task_id, t]));

    const estimates = byType('estimate').sort(byCreated);
    const current = estimates.find(o => o.statusDates.accepted) || estimates[estimates.length - 1] || null;
    const materials = byType('material');
    const deliverables = byType('deliverable');

    return {
      job: byType('job')[0] || null,
      deliverableCount: deliverables.length,
      deliverableEdits: deliverables.reduce((n, o) => n + o.edits, 0),
      currentEstimate: current,
      priorEstimateCount: estimates.length - (current ? 1 : 0),
      tasks: byType('task').sort(byCreated).map(o => ({ ...o, detail: taskDetail.get(o.id) || null })),
      materialCount: materials.length,
      materialsConsumed: materials.filter(o => o.statusDates.consumed).length,
      invoices: byType('invoice').sort(byCreated),
      shipments: byType('shipment').sort(byCreated),
    };
  });

  // Color group per object type; change orders share the estimate tint.
  function typeClass(objectType) {
    return 'ot-' + (objectType === 'changeorder' ? 'estimate' : objectType);
  }

  // Minute-level timestamp (seconds are noise here).
  function fmtWhen(d) {
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
  }

  // --- Grouping: bundle consecutive same-object entries within a minute ---
  const BUNDLE_MS = 60000;

  function sameObject(a, b) {
    return a.object_type === b.object_type && a.object_id === b.object_id;
  }

  let groups = $derived.by(() => {
    const out = [];
    for (const e of entries) {
      const grp = out[out.length - 1];
      const prev = grp && grp[grp.length - 1];
      if (prev && sameObject(prev, e) && prev.username === e.username
          && Math.abs(prev.when - e.when) <= BUNDLE_MS) {
        grp.push(e);
      } else {
        out.push([e]);
      }
    }
    return out;
  });

  // Flatten a group into individual changes ("subheadings"). One audit entry
  // that changed several fields contributes one item per field.
  function groupItems(group) {
    const items = [];
    for (const entry of group) {
      const c = entry.changes || {};
      if (entry.entry_type === 'note') {
        items.push({ key: `${entry.id}-note`, kind: 'note', text: entry.text });
      } else if (c._action) {
        items.push({ key: `${entry.id}-action`, kind: 'action', text: c._action });
      } else if (c._created) {
        items.push({ key: `${entry.id}-created`, kind: 'created' });
      } else {
        for (const f of diffFields(entry)) {
          items.push({ key: `${entry.id}-${f.field}`, kind: 'diff', entryId: entry.id, ...f });
        }
      }
    }
    return items;
  }

  // --- Field-diff rendering (From/To + long-value popover) ---
  const LONG_LEN = 100;
  let openPopover = $state(null); // `${entryId}:${field}` of the open popover

  function popKey(entryId, field) {
    return `${entryId}:${field}`;
  }
  function togglePopover(entryId, field) {
    const k = popKey(entryId, field);
    openPopover = openPopover === k ? null : k;
  }

  function fmtVal(v) {
    return v == null ? '(empty)' : String(v);
  }
  function isLong(v) {
    const s = v == null ? '' : String(v);
    return s.length > LONG_LEN || s.includes('\n');
  }
  function previewVal(v, n = 120) {
    const s = (v == null ? '' : String(v)).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n) + '…' : s;
  }
  function diffFields(entry) {
    const c = entry.changes || {};
    return Object.entries(c)
      .filter(([k]) => !k.startsWith('_'))
      .map(([field, v]) => ({
        field,
        old: v?.old ?? null,
        new: v?.new ?? null,
        long: isLong(v?.old) || isLong(v?.new),
      }));
  }

  async function addNote() {
    const text = noteText.trim();
    if (!text) return;
    saving = true;
    noteError = '';
    noteFields = {};
    try {
      await api.post(`/api/jobs/${jobId}/notes/`, { text });
      noteText = '';
      await load();
      onJobChange();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { noteError = t.message; noteFields = t.fields; }
    } finally {
      saving = false;
    }
  }
</script>

<div class="page">
  {#if loading}
    <p>Loading…</p>
  {:else if loadError}
    <p class="err">{loadError}</p>
  {:else}
    <div class="page-body">
    <header class="page-header">
      <h2>History</h2>
    </header>

    <div class="body">
      <div class="tabs" role="tablist">
        <button class:active={activeTab === 'timeline'} onclick={() => (activeTab = 'timeline')}>Timeline</button>
        <button class:active={activeTab === 'summary'} onclick={() => (activeTab = 'summary')}>Summary</button>
      </div>

      {#if activeTab === 'timeline'}
      <div class="add-note">
        <textarea bind:value={noteText} rows="2" placeholder="Add a note…"></textarea>
        <button onclick={addNote} disabled={saving || !noteText.trim()}>Add Note</button>
      </div>
      <FieldError errors={noteFields} field="text" />
      <FormMessage error={noteError} />

      {#if groups.length > 0}
        <ul class="timeline">
          {#each groups as group (group[0].id)}
            {@const head = group[0]}
            <li class="entry {typeClass(head.object_type)}">
              <div class="entry-meta">
                {#if head.source_link}
                  <a class="source" href={head.source_link}>{head.source_label || head.object_type}</a>
                {:else}
                  <span class="source">{head.source_label || head.object_type}</span>
                {/if}
                <span class="stamp">
                  <span class="when">{fmtWhen(head.when)}</span>
                  <span class="who">{head.username || 'System'}</span>
                </span>
              </div>
              <div class="entry-body">
                {#each groupItems(group) as item (item.key)}
                  {#if item.kind === 'diff'}
                    {#if item.long}
                      <div class="diff diff-long">
                        <div class="diff-head">
                          <span class="diff-field">{item.field} changed</span>
                          <div class="pop-wrap">
                            <button class="pop-trigger" type="button" onclick={() => togglePopover(item.entryId, item.field)}>
                              {openPopover === popKey(item.entryId, item.field) ? 'Hide full' : 'Show full'}
                            </button>
                            {#if openPopover === popKey(item.entryId, item.field)}
                              <button class="pop-backdrop" type="button" aria-label="Close" onclick={() => (openPopover = null)}></button>
                              <div class="popover" role="dialog" aria-label="{item.field} full text">
                                <div class="pop-section">
                                  <div class="pop-label">From</div>
                                  <div class="pop-val preserve-breaks">{fmtVal(item.old)}</div>
                                </div>
                                <div class="pop-section">
                                  <div class="pop-label">To</div>
                                  <div class="pop-val preserve-breaks">{fmtVal(item.new)}</div>
                                </div>
                              </div>
                            {/if}
                          </div>
                        </div>
                        <div class="ft-row"><span class="ft-label">From</span><span class="ft-prev">{previewVal(item.old)}</span></div>
                        <div class="ft-row"><span class="ft-label">To</span><span class="ft-prev">{previewVal(item.new)}</span></div>
                      </div>
                    {:else}
                      <div class="diff diff-short">
                        <span class="diff-field">{item.field}</span>:
                        <span class="val">{fmtVal(item.old)}</span>
                        <span class="arrow">→</span>
                        <span class="val">{fmtVal(item.new)}</span>
                      </div>
                    {/if}
                  {:else if item.kind === 'note'}
                    <div class="item-note preserve-breaks">{item.text}</div>
                  {:else if item.kind === 'action'}
                    <div class="item-line preserve-breaks">{item.text}</div>
                  {:else}
                    <div class="item-line">created</div>
                  {/if}
                {/each}
              </div>
            </li>
          {/each}
        </ul>
      {:else}
        <p>No history yet.</p>
      {/if}
      {/if}

      {#if activeTab === 'summary'}
      <div class="summary">
        {#if summary.job}
          <section class="sum-sec">
            <h3>Job</h3>
            <p>{summary.job.label} {milestones(summary.job.created, summary.job.statusDates, [['approved', 'approved'], ['work_complete', 'work complete'], ['completed', 'completed'], ['rejected', 'rejected'], ['cancelled', 'cancelled']])}</p>
            {#if summary.job.edits > 0}
              <p class="muted">Edited {summary.job.edits} time{summary.job.edits === 1 ? '' : 's'} (name / description)</p>
            {/if}
            {#if summary.deliverableCount > 0}
              <p class="muted">{summary.deliverableCount} deliverable{summary.deliverableCount === 1 ? '' : 's'}{#if summary.deliverableEdits > 0}, edited {summary.deliverableEdits} time{summary.deliverableEdits === 1 ? '' : 's'}{/if}</p>
            {/if}
          </section>
        {/if}

        <section class="sum-sec">
          <h3>Estimates</h3>
          {#if summary.currentEstimate}
            <p>Current estimate {summary.currentEstimate.label} {milestones(summary.currentEstimate.created, summary.currentEstimate.statusDates, [['open', 'sent'], ['accepted', 'accepted'], ['rejected', 'rejected'], ['expired', 'expired'], ['superseded', 'superseded']])}</p>
            {#if summary.priorEstimateCount > 0}
              <p class="muted">{summary.priorEstimateCount} prior estimate{summary.priorEstimateCount === 1 ? '' : 's'}</p>
            {/if}
          {:else}
            <p class="muted">No estimates.</p>
          {/if}
        </section>

        {#if summary.tasks.length > 0}
          <section class="sum-sec">
            <h3>Tasks</h3>
            {#each summary.tasks as t (t.id)}
              <p>{t.detail?.name || t.label} — {milestones(t.created, t.statusDates, [['complete', 'completed']])}{taskExtra(t.detail)}</p>
            {/each}
          </section>
        {/if}

        {#if summary.materialCount > 0}
          <section class="sum-sec">
            <h3>Materials</h3>
            <p class="muted">{summary.materialCount} material{summary.materialCount === 1 ? '' : 's'}{#if summary.materialsConsumed > 0}, {summary.materialsConsumed} used{/if}</p>
          </section>
        {/if}

        {#if summary.invoices.length > 0}
          <section class="sum-sec">
            <h3>Invoices</h3>
            {#each summary.invoices as inv (inv.id)}
              <p>{inv.label} {milestones(inv.created, inv.statusDates, [['open', 'sent'], ['paid', 'paid']])}</p>
            {/each}
          </section>
        {/if}

        {#if summary.shipments.length > 0}
          <section class="sum-sec">
            <h3>Shipments</h3>
            {#each summary.shipments as s (s.id)}
              <p>{s.label} {milestones(s.created, s.statusDates, [['picked_up', 'picked up']])}</p>
            {/each}
          </section>
        {/if}
      </div>
      {/if}
    </div>
  </div>
  {/if}
</div>

<style>
  .page { padding: 0 0 20px 0; }
  .page-header { padding: 0; }
  .page-header h2 { margin-top: 16px; margin-bottom: 4px; }
  .body { max-width: 820px; padding: 0 24px; }
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid #d1d5db; margin: 12px 0 16px; }
  .tabs button {
    border: 1px solid transparent; border-bottom: none; background: none;
    padding: 6px 14px; cursor: pointer; font-size: 14px; color: #555;
    border-radius: 6px 6px 0 0; margin-bottom: -1px;
  }
  .tabs button.active {
    color: #1f2937; font-weight: 600;
    border-color: #d1d5db; background: #fff; border-bottom: 1px solid #fff;
  }

  .summary .sum-sec { margin: 0 0 18px; }
  .summary h3 { font-size: 14px; margin: 0 0 4px; color: #1f2937; }
  .summary p { margin: 2px 0; }
  .summary .muted { color: #6b7280; font-size: 13px; }

  .add-note { margin: 12px 0 20px; }
  .add-note textarea { width: 100%; box-sizing: border-box; }
  .timeline { list-style: none; padding: 0; margin: 0; }
  .entry { padding: 8px 10px; border-bottom: 1px solid rgba(0, 0, 0, 0.06); }

  /* Background tint by object type. Estimates + change orders share a tint.
     A balanced spread across the spectrum — one hue family each. */
  .ot-task { background: #f7d3d6; }        /* red / rose */
  .ot-material { background: #fbe0c6; }    /* orange */
  .ot-estimate { background: #fcf1c6; }    /* yellow / amber */
  .ot-invoice { background: #dcf1d8; }     /* green */
  .ot-shipment { background: #d4eef0; }    /* teal */
  .ot-job { background: #dde7f5; }         /* blue */
  .ot-deliverable { background: #e7dcf6; } /* purple */
  .entry-meta { display: flex; gap: 10px; font-size: 13px; color: #555; align-items: baseline; }
  .entry-meta .source { font-weight: 600; color: #1f2937; }
  .entry-meta .stamp { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; line-height: 1.3; }
  .entry-meta .who { color: #777; }
  .entry-body { margin-top: 2px; }
  .entry-body > * + * { margin-top: 5px; }
  .item-note { font-style: italic; }
  .item-line { margin: 1px 0; }
  .err { color: #c00; padding: 0 24px; }

  /* Field diffs */
  .diff { margin: 1px 0; }
  .diff-field { font-weight: 600; color: #374151; }
  .diff-short .val { color: #111; }
  .diff-short .arrow { color: #9ca3af; }
  .diff-long { margin: 3px 0; }
  .diff-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .ft-row { display: flex; gap: 8px; align-items: baseline; }
  .ft-label {
    flex: 0 0 2.5em; color: #6b7280; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.03em;
  }
  .ft-prev { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #374151; }

  /* Long-value popover */
  .pop-wrap { position: relative; flex: 0 0 auto; }
  .pop-trigger { font-size: 12px; padding: 1px 8px; cursor: pointer; }
  .pop-backdrop {
    position: fixed; inset: 0; z-index: 40;
    background: transparent; border: 0; padding: 0; cursor: default;
  }
  .popover {
    position: absolute; top: calc(100% + 4px); right: 0; z-index: 50;
    width: min(480px, 80vw); max-height: 50vh; overflow: auto;
    background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18); padding: 10px 12px;
  }
  .pop-section + .pop-section { margin-top: 8px; border-top: 1px solid #eee; padding-top: 8px; }
  .pop-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em;
    color: #6b7280; margin-bottom: 2px;
  }
  .pop-val { font-size: 13px; color: #111; }
</style>
