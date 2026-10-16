import App from './App.svelte';
import { mount } from 'svelte';
import './css/app.css';
import { viewMode } from './stores/viewMode.js';
import { layout } from './stores/layout.js';

// Density (user preference) and layout (device fact) are mirrored onto <body>
// as data attributes so plain CSS can key off either axis without a component.
viewMode.subscribe((mode) => {
  document.body.dataset.viewMode = mode;
});

// This permanent subscription also keeps the readable store's matchMedia
// listener alive for the lifetime of the app.
layout.subscribe((mode) => {
  document.body.dataset.layout = mode;
});

mount(App, {
  target: document.getElementById('app'),
});
