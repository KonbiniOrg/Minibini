<script>
  import { user } from '../stores/auth.js';
  import { viewMode, toggleViewMode } from '../stores/viewMode.js';
</script>

<h2>{$user?.username} Profile</h2>

<p>
  View mode: <strong>{$viewMode}</strong>
  — <a href="#" onclick={(e) => { e.preventDefault(); toggleViewMode(); }}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </a>
</p>
