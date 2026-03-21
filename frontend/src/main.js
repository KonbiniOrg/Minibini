import App from './App.svelte';
import { mount } from 'svelte';
import './css/app.css';
import { viewMode } from './stores/viewMode.js';

viewMode.subscribe((mode) => {
  document.body.dataset.viewMode = mode;
});

async function init() {
  const params = new URLSearchParams(window.location.search);
  if (params.has('autologin')) {
    try {
      await fetch('/api/auth/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username: 'dev_user', password: 'dev_password' }),
      });
    } catch (e) {
      // dev_user doesn't exist — ignore, app will show unauthenticated state
    }
  }

  mount(App, {
    target: document.getElementById('app'),
  });
}

init();
