// Persona → storageState path + user facts (design doc §4.2, from the
// seed's real users). auth.setup.js logs each persona in once; specs pick
// a persona with:
//   test.use({ storageState: personas.worker.storageState });
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const E2E_PASSWORD = 'e2e_password';

const authDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '.auth');

export const personas = {
  worker: {
    username: 'schen',
    displayName: 'Schen Workerbee',
    atoms: [],
    storageState: path.join(authDir, 'worker.json'),
  },
  timeManager: {
    username: 'arivera',
    displayName: 'Arivera Timer',
    atoms: ['can_manage_time'],
    storageState: path.join(authDir, 'timeManager.json'),
  },
  financials: {
    username: 'jkim',
    displayName: 'Jkim Accountant',
    atoms: ['can_manage_financials', 'can_manage_jobs'],
    storageState: path.join(authDir, 'financials.json'),
  },
  configAdmin: {
    username: 'tbrooks',
    displayName: 'Tbrooks UsersNotJobs',
    atoms: ['can_manage_config', 'can_manage_time'],
    storageState: path.join(authDir, 'configAdmin.json'),
  },
  superuser: {
    username: 'dev_user',
    displayName: 'Fake Owner',
    atoms: [],
    isSuperuser: true,
    storageState: path.join(authDir, 'superuser.json'),
  },
};
