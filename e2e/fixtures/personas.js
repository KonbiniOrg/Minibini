// Persona → storageState path + user facts (docs/designs/e2e-testing.md §2).
// Usernames are the permission-names that prepare_seed.py's PERSONA_RENAMES
// map stamps onto the seed's dev-DB users (schen, arivera, jkim, tbrooks,
// dev_user) — keep the two in sync. auth.setup.js logs each persona in once;
// specs pick a persona with:
//   test.use({ storageState: personas.worker.storageState });
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const E2E_PASSWORD = 'e2e_password';

const authDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '.auth');

export const personas = {
  worker: {
    username: 'worker',
    displayName: 'Worker NoAtoms',
    atoms: [],
    storageState: path.join(authDir, 'worker.json'),
  },
  timemgr: {
    username: 'timemgr',
    displayName: 'Time Manager',
    atoms: ['can_manage_time'],
    storageState: path.join(authDir, 'timemgr.json'),
  },
  finjobs: {
    username: 'finjobs',
    displayName: 'Financials AndJobs',
    atoms: ['can_manage_financials', 'can_manage_jobs'],
    storageState: path.join(authDir, 'finjobs.json'),
  },
  configtime: {
    username: 'configtime',
    displayName: 'Config AndTime',
    atoms: ['can_manage_config', 'can_manage_time'],
    storageState: path.join(authDir, 'configtime.json'),
  },
  superuser: {
    username: 'superuser',
    displayName: 'Super User',
    atoms: [],
    isSuperuser: true,
    storageState: path.join(authDir, 'superuser.json'),
  },
};
