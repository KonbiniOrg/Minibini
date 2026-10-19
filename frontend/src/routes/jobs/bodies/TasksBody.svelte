<script>
  // Tasks section body. The job + contact are owned by JobWorkspace and
  // passed in; this body only hosts the section panel. (Was JobTaskListPage.)
  import TasksPanel from '../../../components/tasks/TasksPanel.svelte';
  let { job, onJobChange = () => {} } = $props();
</script>

<TasksPanel {job} {onJobChange} />
