<script>
  // Draft-time composition of a new document line from N selected atoms
  // (estimating-structure Task 8: "bundle into a line"). Shows the selected
  // atoms read-only (kind/description/qty/amount + their summed total),
  // then authoring fields the user reviews/edits before committing:
  // description, qty, units, price.
  //
  // Keep-the-total gesture (ON by default): while `keepTotal` is checked,
  // editing qty re-derives price = total ÷ qty (rounded to cents, same as
  // fmtMoney's display precision) so the line's amount always matches the
  // selected atoms' summed total. Editing price directly is a one-way exit
  // from the coupling — it unchecks keepTotal rather than reverse-deriving
  // qty, which would risk divide-by-zero/qty-churn for no real benefit
  // (RM's simpler rule: qty->price only).
  //
  // Self-contained like AdjustmentModal/LineItemModal: owns its own POST to
  // `${apiBase}/line-items-from-atoms/` with {atoms, overrides}. A 409 claim
  // conflict is handed to the caller via onConflict — only the parent view
  // knows how to refresh its sourcePool/selected state, so that dance stays
  // there (mirrors EstimateEditView/COEditView's handleMutationError)
  // instead of being duplicated here.
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import { fmtMoney } from '../../lib/taskTotals.js';
  import { atomKindTag, formatQtyUnits } from '../../lib/format.js';
  import Modal from '../Modal.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  let {
    open = false,
    atoms = [],           // raw source-pool atom shape: {type, id, description, qty, units, rate, amount}
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
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  let total = $derived(
    atoms.reduce((sum, a) => sum + (Number(a.amount) || 0), 0)
  );
  let qtyValid = $derived(qty !== '' && Number.isFinite(Number(qty)) && Number(qty) > 0);

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

  $effect(() => {
    if (open) {
      keepTotal = true;
      formError = '';
      fieldErrs = {};
      if (atoms.length === 1) {
        const a = atoms[0];
        description = a.description || '';
        qty = a.qty ?? '';
        units = a.units || 'none';
        price = a.rate ?? '';
      } else {
        const seed = deriveMultiAtomSeed(atoms, total);
        description = seed.description;
        qty = seed.qty;
        units = seed.units;
        price = seed.price;
      }
    }
  });

  function onQtyInput(value) {
    qty = value;
    if (keepTotal) {
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

  async function create() {
    if (!qtyValid || busy) return;
    busy = true;
    formError = '';
    fieldErrs = {};
    try {
      const newLine = await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: atoms.map((a) => ({ type: a.type, id: a.id })),
        overrides: { description, qty, units, price },
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
          {#each atoms as atom (`${atom.type}:${atom.id}`)}
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
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
