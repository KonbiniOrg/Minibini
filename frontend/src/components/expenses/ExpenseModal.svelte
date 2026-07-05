<script>
  import ExpenseForm from './ExpenseForm.svelte';
  import Modal from '../Modal.svelte';

  let {
    open = false,
    expense = null,
    initialJob = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();
</script>

<!-- Enter is owned by ExpenseForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="720px">
      <h3>{expense ? 'Edit Expense' : 'Add Expense'}</h3>
      <ExpenseForm
        {expense}
        {initialJob}
        onSaved={(exp) => onSaved(exp)}
        onCancel={onClose}
      />
</Modal>


<style>
</style>
