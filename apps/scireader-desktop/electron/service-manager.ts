import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';

export const REFLOW_BASE_URL = 'http://127.0.0.1:27621';

let serviceProcess: ChildProcessWithoutNullStreams | null = null;

export function workspaceRoot(appPath: string) {
  if (process.env.SCIREADER_WORKSPACE_ROOT) {
    return process.env.SCIREADER_WORKSPACE_ROOT;
  }
  const seeds = [process.cwd(), appPath, __dirname];
  for (const seed of seeds) {
    let current = path.resolve(seed);
    for (let i = 0; i < 8; i++) {
      if (fs.existsSync(path.join(current, 'reflow-service', 'service.py'))) {
        return current;
      }
      const parent = path.dirname(current);
      if (parent === current) break;
      current = parent;
    }
  }
  return path.resolve(appPath, '..', '..');
}

export function pythonExecutable(root: string) {
  const venv = path.join(root, 'tools', 'reflow-venv', 'Scripts', 'python.exe');
  return fs.existsSync(venv) ? venv : 'python';
}

async function health(timeout = 1200) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${REFLOW_BASE_URL}/health`, { signal: controller.signal });
    return response.ok;
  }
  catch {
    return false;
  }
  finally {
    clearTimeout(timer);
  }
}

export async function ensureReflowService(root: string) {
  if (await health()) {
    return { ok: true, started: false, url: REFLOW_BASE_URL };
  }
  const script = path.join(root, 'reflow-service', 'service.py');
  if (!fs.existsSync(script)) {
    return { ok: false, started: false, url: REFLOW_BASE_URL, error: `Missing ${script}` };
  }
  serviceProcess = spawn(pythonExecutable(root), [script], {
    cwd: root,
    windowsHide: true,
    env: { ...process.env, REFLOW_PORT: '27621' }
  });
  serviceProcess.stdout.on('data', data => console.log(`[reflow] ${data}`));
  serviceProcess.stderr.on('data', data => console.warn(`[reflow] ${data}`));
  serviceProcess.on('exit', () => {
    serviceProcess = null;
  });
  for (let i = 0; i < 30; i++) {
    if (await health(1000)) {
      return { ok: true, started: true, url: REFLOW_BASE_URL };
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  return { ok: false, started: true, url: REFLOW_BASE_URL, error: 'reflow-service did not become healthy' };
}

export function stopReflowService() {
  if (serviceProcess && !serviceProcess.killed) {
    serviceProcess.kill();
  }
  serviceProcess = null;
}
