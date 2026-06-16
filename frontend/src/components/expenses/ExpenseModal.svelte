<script>
  import ExpenseForm from './ExpenseForm.svelte';

  let {
    open = false,
    expense = null,
    initialJob = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{expense ? 'Edit Expense' : 'Add Expense'}</h3>
      <ExpenseForm
        {expense}
        {initialJob}
        onSaved={(exp) => onSaved(exp)}
        onCancel={onClose}
      />
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.4);
    display: flex; align-items: flex-start; justify-content: center;
    z-index: var(--z-modal); overflow-y: auto; padding: 2em 0;
  }
  .modal {
    background: white; padding: 1.5em; border: 2px solid #333;
    max-width: 480px; width: 90%;
  }
</style>
