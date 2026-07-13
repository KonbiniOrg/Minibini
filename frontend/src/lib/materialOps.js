// Shared per-material operations — the handler halves of the material
// action set, usable from any surface that renders MaterialRow (job task
// list, task detail page). Each takes the material and a `reload` callback
// and owns its own error surfacing, mirroring the original TasksPanel
// handlers. (The Order and Mark-received flows need modals — they live in
// components/materials/MaterialFulfillmentModals.svelte.)
import { api, errorMessage } from './api.js';
import { showError } from '../stores/messages.js';

export async function consumeMaterial(material, reload) {
  // No confirm: reversible via the sibling Restock action.
  try {
    await api.post(`/api/materials/${material.material_id}/consume/`, {});
    await reload();
  } catch (e) {
    showError(errorMessage(e, 'Could not consume.'));
  }
}

export async function restockMaterial(material, reload) {
  // Same predicate as MaterialRow.restockLabel: with stock on hand this
  // reads as returning it; otherwise it's a release of the planned quantity.
  const verb = material.inventory_item != null && Number(material.qty_on_hand) > 0
    ? 'Restock' : 'Release';
  const raw = window.prompt(`${verb} quantity (max ${material.quantity}):`, material.quantity);
  if (raw === null) return;
  const quantity = raw.trim();
  if (!quantity) return;
  try {
    await api.post(`/api/materials/${material.material_id}/restock/`, { quantity });
    await reload();
  } catch (e) {
    showError(errorMessage(e, 'Could not restock.'));
  }
}

export async function drawMoreMaterial(material, reload) {
  const raw = window.prompt('Draw more quantity:', '1');
  if (raw === null) return;
  const quantity = raw.trim();
  if (!quantity) return;
  try {
    await api.post(`/api/materials/${material.material_id}/draw-more/`, { quantity });
    await reload();
  } catch (e) {
    showError(errorMessage(e, 'Could not draw more.'));
  }
}

export async function moveMaterial(material, taskId, reload) {
  try {
    await api.post(`/api/materials/${material.material_id}/assign-task/`, { task: taskId });
    await reload();
  } catch (e) {
    showError(errorMessage(e, 'Could not move material.'));
  }
}
