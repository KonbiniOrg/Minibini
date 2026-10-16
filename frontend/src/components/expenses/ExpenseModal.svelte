<script>
  import ExpenseForm from './ExpenseForm.svelte';
  import Modal from '../Modal.svelte';

  let {
    open = false,
    expense = null,
    initialJob = null,
    initialMaterial = null,
    lockPurchasedByToSelf = false,  // home card: the worker submits for themselves
    onSaved = () => {},
    onClose = () => {},
  } = $props();
</script>

<!-- Enter is owned by ExpenseForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="720px">
      <h3>{expense ? 'Edit Expense' : (initialMaterial ? 'Attach Expense' : 'Add Expense')}</h3>
      <ExpenseForm
        {expense}
        {initialJob}
        {initialMaterial}
        {lockPurchasedByToSelf}
        onSaved={(exp) => onSaved(exp)}
        onCancel={onClose}
      />
</Modal>


<style>
</style>
