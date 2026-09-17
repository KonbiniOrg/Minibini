<script>
  // Draft-time composition of a new document line from N selected atoms
  // (estimating-structure Task 8: "bundle into a line"). Shows the selected
  // atoms read-only (kind/description/qty/amount + their summed total),
  // then authoring fields the user reviews/edits before committing:
  // description, qty, units, price.
  //
  // Interpretation choice (per-unit-lines spec §5, minimal-additions phase —
  // full modal restructure is a later, RM-gated phase): the atom values the
  // user selected describe either ONE UNIT (per-unit — the DEFAULT) or THE
  // WHOLE LINE (today's original behavior). Same inputs, opposite derivation
  // direction, never both:
  //
  // - one-unit (perUnit=true): price seeds to the summed CURRENT atom
  //   amounts (that sum IS the per-unit price under this reading); qty seeds
  //   EMPTY (a real per-unit multiplier has to be typed, never assumed); the
  //   keep-total control doesn't apply and is hidden; the line total is
  //   purely derived (qty * price) and shown live. Once qty is valid, a
  //   preview table lists each atom's before -> after value at that qty —
  //   the reinterpretation and the coming atom stamps must be unmissable
  //   before Create (spec §12 Q1). A task atom with no existing schedule
  //   time (est_worker_time) additionally offers an optional per-unit
  //   duration input; a filled value rides along as that atom's
  //   `per_unit_worker_time` in the POST body.
  // - whole-line (perUnit=false): exactly today's UI — keep-total ON by
  //   default, editing qty re-derives price = total / qty.
  //
  // Keep-the-total gesture (whole-line mode only, ON by default): while
  // `keepTotal` is checked, editing qty re-derives price = total ÷ qty
  // (rounded to cents, same as fmtMoney's display precision) so the line's
  // amount always matches the selected atoms' summed total. Editing price
  // directly is a one-way exit from the coupling — it unchecks keepTotal
  // rather than reverse-deriving qty, which would risk divide-by-zero/qty-
  // churn for no real benefit (RM's simpler rule: qty->price only).
  //
  // Self-contained like AdjustmentModal/LineItemModal: owns its own POST to
  // `${apiBase}/line-items-from-atoms/` with {atoms, overrides, per_unit}. A
  // 409 claim conflict is handed to the caller via onConflict — only the
  // parent view knows how to refresh its sourcePool/selected state, so that
  // dance stays there (mirrors EstimateEditView/COEditView's
  // handleMutationError) instead of being duplicated here.
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import { fmtMoney } from '../../lib/taskTotals.js';
  import {
    atomKindTag, formatQtyUnits, formatDuration, durationToHours,
    parseDurationToISO, parseDurationToHours,
  } from '../../lib/format.js';
  import Modal from '../Modal.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let {
    open = false,
    atoms = [],           // raw source-pool atom shape: {type, id, description, qty, units, rate, amount, worker_time?}
    apiBase = '',          // e.g. '/api/estimates/7' or '/api/change-orders/7'
    onCreated = () => {},  // called with the created line item on success
    onConflict = () => {}, // called with the error on a 409 claim conflict
    onClose = () => {},
  } = $props();

  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let keepTotal = $state(true);
  let perUnit = $state(true); // one-unit is the modal default (spec §5)
  let perUnitWorkerTimes = $state({}); // atomKey -> raw user input string
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  function atomKey(a) {
    return `${a.type}:${a.id}`;
  }

  let total = $derived(
    atoms.reduce((sum, a) => sum + (Number(a.amount) || 0), 0)
  );
  let qtyNum = $derived(Number(qty) || 0);
  let qtyValid = $derived(qty !== '' && Number.isFinite(Number(qty)) && Number(qty) > 0);
  let priceNum = $derived(Number(price) || 0);
  let lineTotal = $derived(qtyValid ? qtyNum * priceNum : null);

  // Mirrors BaseWizardService._uniform_money_bundle (apps/core/wizard.py) —
  // see that method's docstring for the authoritative rule. This is an
  // APPROXIMATION: the source-pool atom shape only exposes each task's
  // effective_rate + unit_label, not the raw stamped `rate`/
  // `active_modifiers` the backend actually compares, so this checks
  // "all tasks, same units, same effective rate" instead. That's fine for
  // seeding purposes only — the modal always sends description/qty/units/
  // price as explicit overrides (WYSIWYG), so a seed that doesn't exactly
  // match the backend's own (now-unused, once overrides are present)
  // derivation can never cause the created line to differ from what's
  // displayed. If wizard.py's uniformity rule changes, check this too.
  function deriveMultiAtomSeed(selectedAtoms, summedTotal) {
    const allTasks = selectedAtoms.every((a) => a.type === 'task');
    const units = new Set(selectedAtoms.map((a) => a.units || 'none'));
    const rates = new Set(selectedAtoms.map((a) => a.rate));
    if (allTasks && selectedAtoms[0].rate != null && units.size === 1 && rates.size === 1) {
      const qty = selectedAtoms.reduce((sum, a) => sum + (Number(a.qty) || 0), 0);
      return {
        // Round to cents-equivalent precision like the lump branch's
        // total.toFixed(2) below — plain float addition of two-decimal
        // quantities (e.g. three 1.10s) produces binary-float garbage
        // ("3.3000000000000003") that a DecimalField(decimal_places=2)
        // rejects on submit if the user never touches the field.
        description: '', qty: qty.toFixed(2),
        units: selectedAtoms[0].units || 'none', price: selectedAtoms[0].rate,
      };
    }
    // Not a uniform task bundle (mixed atom types, or differing units/rate)
    // — plain lump sum. Keep-total's qty->price re-derivation is the tool
    // for reshaping this, so there's no need to guess further here.
    return { description: '', qty: '1', units: 'none', price: summedTotal.toFixed(2) };
  }

  // description/units seed ONCE, on open, from the atom(s) — they are not
  // part of the interpretation semantics (unlike qty/price, which flip
  // derivation direction between the two readings). Reused by both
  // seedWholeLine/seedPerUnit below so a fresh open and a first render
  // agree.
  function seedDescriptionAndUnits() {
    if (atoms.length === 1) {
      description = atoms[0].description || '';
      units = atoms[0].units || 'none';
    } else {
      const seed = deriveMultiAtomSeed(atoms, total);
      description = seed.description;
      units = seed.units;
    }
  }

  // Today's whole-line seed: qty/price copy from (or summarize) the atoms'
  // own current values. Does NOT touch description/units — those are
  // seeded once, on open, and stay as authored across an interpretation
  // switch.
  function seedWholeLine() {
    keepTotal = true;
    if (atoms.length === 1) {
      const a = atoms[0];
      qty = a.qty ?? '';
      price = a.rate ?? '';
    } else {
      const seed = deriveMultiAtomSeed(atoms, total);
      qty = seed.qty;
      price = seed.price;
    }
  }

  // One-unit seed: qty empties (must be typed) and price becomes the
  // summed CURRENT atom amounts (now read as a per-unit price). Same
  // description/units carve-out as seedWholeLine.
  function seedPerUnit() {
    qty = '';
    price = total.toFixed(2);
  }

  function setInterpretation(newPerUnit) {
    if (newPerUnit === perUnit) return;
    perUnit = newPerUnit;
    if (perUnit) {
      seedPerUnit();
    } else {
      seedWholeLine();
    }
  }

  $effect(() => {
    if (open) {
      formError = '';
      fieldErrs = {};
      perUnitWorkerTimes = {};
      perUnit = true;
      seedDescriptionAndUnits();
      seedPerUnit();
    }
  });

  function onQtyInput(value) {
    qty = value;
    if (!perUnit && keepTotal) {
      const q = Number(value);
      if (value !== '' && Number.isFinite(q) && q > 0) {
        price = (total / q).toFixed(2);
      }
    }
  }

  function onPriceInput(value) {
    price = value;
    keepTotal = false;
  }

  function onKeepTotalChange(checked) {
    keepTotal = checked;
    if (checked) {
      const q = Number(qty);
      if (qty !== '' && Number.isFinite(q) && q > 0) {
        price = (total / q).toFixed(2);
      }
    }
  }

  function onWorkerTimeInput(key, value) {
    perUnitWorkerTimes = { ...perUnitWorkerTimes, [key]: value };
  }

  // hours (float) -> a DRF-DurationField-style "H:MM:SS" string, so
  // formatDuration (which already parses that shape) renders it.
  function hoursToDurationStr(hours) {
    const totalMinutes = Math.round(hours * 60);
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return `${h}:${String(m).padStart(2, '0')}:00`;
  }

  function formatHours(hours) {
    return formatDuration(hoursToDurationStr(hours));
  }

  // Per-atom preview: the atom's current qty scaled by the entered qty
  // (the per-unit multiplier) — "0.75 hour -> 7.50 hour" at qty 10, or
  // "4 BF -> 40 BF" (no trailing zeros for a whole-number result).
  function formatScaledQty(value) {
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
  }

  function scaledQtyDisplay(atom) {
    const after = (Number(atom.qty) || 0) * qtyNum;
    return formatQtyUnits(formatScaledQty(after), atom.units);
  }

  // For a task atom that already carries a schedule commitment
  // (est_worker_time): before/after display, scaled by qty — the atom
  // stamp this preview announces (spec §5.2: est_worker_time multiplies
  // whenever the task HAS one, regardless of unit denomination).
  function existingScheduleAfter(atom) {
    const hours = durationToHours(atom.worker_time);
    if (hours === null) return null;
    return formatHours(hours * qtyNum);
  }

  // For a task atom with NO existing schedule time: the optional per-unit
  // duration input's live before/after preview, once a valid value is typed.
  function enteredSchedulePreview(atom) {
    const raw = perUnitWorkerTimes[atomKey(atom)];
    if (!raw) return null;
    const hours = parseDurationToHours(raw);
    if (!hours) return null;
    return { before: formatHours(hours), after: formatHours(hours * qtyNum) };
  }

  async function create() {
    if (!qtyValid || busy) return;
    busy = true;
    formError = '';
    fieldErrs = {};
    try {
      const atomsPayload = atoms.map((a) => {
        const entry = { type: a.type, id: a.id };
        if (perUnit && a.type === 'task' && !a.worker_time) {
          const raw = perUnitWorkerTimes[atomKey(a)];
          if (raw) {
            const iso = parseDurationToISO(raw);
            if (iso) entry.per_unit_worker_time = iso;
          }
        }
        return entry;
      });
      const newLine = await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: atomsPayload,
        overrides: { description, qty, units, price },
        per_unit: perUnit,
      });
      onCreated(newLine);
    } catch (e) {
      if (e?.status === 409) {
        onConflict(e);
        return;
      }
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onCancel={onClose} label="Bundle into line" maxWidth="720px">
<form onsubmit={(e) => { e.preventDefault(); if (!busy) create(); }}>
      <h3>Bundle into line</h3>

      <table class="data-table bundle-atoms">
        <thead>
          <tr>
            <th>Kind</th>
            <th>Description</th>
            <th class="text-right">Qty</th>
            <th class="text-right">Amount</th>
          </tr>
        </thead>
        <tbody>
          {#each atoms as atom (atomKey(atom))}
            <tr>
              <td><small>[{atomKindTag(atom.type)}]</small></td>
              <td>{atom.description}</td>
              <td class="text-right">{formatQtyUnits(atom.qty, atom.units)}</td>
              <td class="text-right">{fmtMoney(atom.amount)}</td>
            </tr>
          {/each}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3" class="text-right"><strong>Total</strong></td>
            <td class="text-right"><strong>{fmtMoney(total)}</strong></td>
          </tr>
        </tfoot>
      </table>

      <fieldset class="interpretation">
        <legend>The values on these tasks and materials are for:</legend>
        <label>
          <input
            type="radio" name="interpretation"
            checked={perUnit}
            onchange={() => setInterpretation(true)}
          >
          one unit — multiply by quantity
        </label>
        <label>
          <input
            type="radio" name="interpretation"
            checked={!perUnit}
            onchange={() => setInterpretation(false)}
          >
          the whole line
        </label>
      </fieldset>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
        </label>
        <FieldError errors={fieldErrs} field="description" />
      </p>
      <p>
        <label><strong>Quantity</strong><br>
          <input
            type="number" step="0.01" min="0"
            value={qty}
            oninput={(e) => onQtyInput(e.target.value)}
          >
        </label>
        <FieldError errors={fieldErrs} field="qty" />
      </p>
      <p>
        <label><strong>Units</strong><br>
          <UnitsSelect bind:value={units} />
        </label>
        <FieldError errors={fieldErrs} field="units" />
      </p>
      <p>
        <label><strong>Price</strong><br>
          <input
            type="number" step="0.01"
            value={price}
            oninput={(e) => onPriceInput(e.target.value)}
          >
        </label>
        <FieldError errors={fieldErrs} field="price" />
      </p>

      {#if perUnit}
        {#if lineTotal !== null}
          <p data-testid="bundle-line-total">Line total: {fmtMoney(lineTotal)}</p>
        {/if}
        {#if qtyValid}
          <table class="data-table bundle-preview" data-testid="bundle-preview">
            <thead>
              <tr>
                <th>Task / material</th>
                <th class="text-right">Per unit → total</th>
              </tr>
            </thead>
            <tbody>
              {#each atoms as atom (atomKey(atom))}
                <tr>
                  <td>{atom.description}</td>
                  <td class="text-right">
                    {formatQtyUnits(atom.qty, atom.units)} → {scaledQtyDisplay(atom)}
                    {#if atom.type === 'task'}
                      {#if atom.worker_time}
                        <br><small>schedule {formatDuration(atom.worker_time)} → {existingScheduleAfter(atom)}</small>
                      {:else}
                        <br>
                        <label>
                          <small>Per-unit schedule time (optional)</small><br>
                          <input
                            type="text" placeholder="e.g. 0:45 or 0.75"
                            value={perUnitWorkerTimes[atomKey(atom)] || ''}
                            oninput={(e) => onWorkerTimeInput(atomKey(atom), e.target.value)}
                          >
                        </label>
                        {#if enteredSchedulePreview(atom)}
                          <br><small>schedule {enteredSchedulePreview(atom).before} → {enteredSchedulePreview(atom).after}</small>
                        {/if}
                      {/if}
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      {:else}
        <p>
          <label>
            <input
              type="checkbox"
              checked={keepTotal}
              onchange={(e) => onKeepTotalChange(e.target.checked)}
            >
            keep total {fmtMoney(total)}
          </label>
        </p>
      {/if}

      <div class="buttons">
        <button type="submit" disabled={busy || !qtyValid}>Create line</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />
</form>
</Modal>

<style>
  .bundle-atoms { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
  .bundle-atoms th, .bundle-atoms td { padding: 4px 8px; }
  .bundle-preview { width: 100%; border-collapse: collapse; margin: 12px 0; }
  .bundle-preview th, .bundle-preview td { padding: 4px 8px; }
  .interpretation { margin-bottom: 12px; }
  .interpretation label { margin-right: 16px; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
