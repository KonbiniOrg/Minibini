<script>
  // Shown on an archived job — a terminal, read-only historical import.
</script>

<div class="archived-banner" role="status">
  <strong>Archived:</strong>
  <span>this job was imported as a historical record and cannot be changed.</span>
</div>

<style>
  /* Pill-sized and sized to its text: it stands in for the status pill in
     the job header's status row (a fixed three-line band), so it must not
     add height or stretch across the titleblock. */
  .archived-banner { background: #e5e7eb; border: 1px solid #d1d5db; color: #4b5563; border-radius: 10px;
    padding: 3px 10px; font-size: 12px; margin: 0; width: fit-content; max-width: 100%; min-width: 0;
    display: flex; gap: 6px; align-items: baseline; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .archived-banner span { overflow: hidden; text-overflow: ellipsis; }
</style>
