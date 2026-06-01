import PortalApp from './PortalApp.svelte';
import { mount } from 'svelte';
import './css/app.css';

mount(PortalApp, {
  target: document.getElementById('portal'),
});
