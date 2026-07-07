<script>
  // Controlled weekly-envelope editor. The PARENT owns saving — this
  // component only reports edits via onchange (explicit Save upstream;
  // never blur-commits to the server).
  //
  //   value        — envelope object ({mon: [["08:00","17:00"]], …}) or null
  //   allowNull    — show "Use shop default" / "Customize" (user surfaces)
  //   onchange(v)  — fired with the new envelope object, or null (reset)
  const { value = null, allowNull = false, onchange } = $props();

  const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const DAY_LABELS = {
    mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu',
    fri: 'Fri', sat: 'Sat', sun: 'Sun',
  };

  function deepCopy(env) {
    const out = {};
    for (const key of DAY_KEYS) {
      out[key] = (env?.[key] ?? []).map(([s, e]) => [s, e]);
    }
    return out;
  }

  function standardWeek() {
    const out = {};
    for (const key of DAY_KEYS) {
      out[key] = ['sat', 'sun'].includes(key) ? [] : [['08:00', '17:00']];
    }
    return out;
  }

  function addInterval(day) {
    const next = deepCopy(value);
    const last = next[day][next[day].length - 1];
    // A sane default: after the previous interval, else the standard day.
    next[day].push(last ? [last[1], '23:00'] : ['08:00', '17:00']);
    onchange(next);
  }

  function removeInterval(day, i) {
    const next = deepCopy(value);
    next[day].splice(i, 1);
    onchange(next);
  }

  function setTime(day, i, which, newTime) {
    const next = deepCopy(value);
    next[day][i][which] = newTime;
    onchange(next);
  }
</script>

{#if allowNull && value === null}
  <div class="env-default">
    <span>Using the shop schedule.</span>
    <button type="button" onclick={() => onchange(standardWeek())}>Customize</button>
  </div>
{:else}
  <div class="env-grid">
    {#each DAY_KEYS as day (day)}
      <div class="env-day">
        <span class="env-label">{DAY_LABELS[day]}</span>
        <div class="env-intervals">
          {#each value[day] ?? [] as interval, i (i)}
            <span class="env-interval">
              <input
                type="time"
                value={interval[0]}
                oninput={(e) => setTime(day, i, 0, e.target.value)}
              />
              –
              <input
                type="time"
                value={interval[1]}
                oninput={(e) => setTime(day, i, 1, e.target.value)}
              />
              <button
                type="button"
                class="env-remove"
                title="Remove this interval"
                onclick={() => removeInterval(day, i)}
              >✕</button>
            </span>
          {/each}
          {#if (value[day] ?? []).length === 0}
            <span class="env-off">Day off</span>
          {/if}
          <button
            type="button"
            class="env-add"
            title="Add a working interval"
            onclick={() => addInterval(day)}
          >+ interval</button>
        </div>
      </div>
    {/each}
  </div>
  {#if allowNull}
    <div class="env-reset">
      <button type="button" onclick={() => onchange(null)}>Use shop default</button>
    </div>
  {/if}
{/if}

<style>
  .env-grid { display: flex; flex-direction: column; gap: 4px; }
  .env-day {
    display: flex; align-items: baseline; gap: 10px;
    padding: 2px 0; border-bottom: 1px solid #f0f0f0;
  }
  .env-label {
    width: 36px; font-size: 12px; font-weight: 600; color: #374151;
    flex-shrink: 0;
  }
  .env-intervals {
    display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
  }
  .env-interval { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; }
  .env-interval input[type="time"] { font-size: 12px; padding: 1px 3px; }
  .env-remove {
    font-size: 10px; padding: 0 5px; line-height: 1.6;
    background: none; border: 1px solid #d1d5db; border-radius: 4px;
    cursor: pointer; color: #6b7280;
  }
  .env-remove:hover { color: #b91c1c; border-color: #fca5a5; }
  .env-add {
    font-size: 11px; padding: 0 6px; background: none;
    border: 1px dashed #d1d5db; border-radius: 4px;
    cursor: pointer; color: #6b7280;
  }
  .env-add:hover { color: #111827; border-color: #9ca3af; }
  .env-off { font-size: 12px; color: #9ca3af; font-style: italic; }
  .env-default {
    display: flex; align-items: center; gap: 10px;
    font-size: 13px; color: #4b5563;
  }
  .env-reset { margin-top: 6px; }
  .env-reset button, .env-default button { font-size: 12px; padding: 2px 8px; }
</style>
