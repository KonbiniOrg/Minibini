<script>
  import TimeEditModal from '../time/TimeEditModal.svelte';
  let { open = false, mode = 'edit', blep = null, taskId = null,
        currentUser, onSaved = () => {}, onClose = () => {} } = $props();
</script>

<TimeEditModal {open} recordType="blep" action={mode} record={blep} {taskId}
  {currentUser} {onSaved} {onClose} />
