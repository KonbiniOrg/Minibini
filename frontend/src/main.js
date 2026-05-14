import App from './App.svelte';
import { mount } from 'svelte';
import './css/app.css';
import { viewMode } from './stores/viewMode.js';

viewMode.subscribe((mode) => {
  document.body.dataset.viewMode = mode;
});

mount(App, {
  target: document.getElementById('app'),
});
