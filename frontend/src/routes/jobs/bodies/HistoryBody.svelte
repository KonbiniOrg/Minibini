<script>
  // History section body. Job owned by JobWorkspace. (Was JobHistoryPage.)
  import JobHistorySection from '../../../components/jobs/JobHistorySection.svelte';
  let { job, onJobChange = () => {} } = $props();
</script>

<JobHistorySection {job} {onJobChange} />
