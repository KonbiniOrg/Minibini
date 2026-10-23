import PortalApp from './PortalApp.svelte';
import { mount } from 'svelte';
import './css/app.css';
// Inter (self-hosted): the app font, via var(--font-sans) in app.css.
import '@fontsource-variable/inter';

mount(PortalApp, {
  target: document.getElementById('portal'),
});
