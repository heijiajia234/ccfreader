import { spawn } from 'node:child_process';
import path from 'node:path';
import { pythonExecutable } from './service-manager';

export async function runStoreCommand<T>(root: string, command: string, payload: Record<string, unknown> = {}): Promise<T> {
  const script = path.join(root, 'apps', 'scireader-desktop', 'scripts', 'scireader_store.py');
  return new Promise((resolve, reject) => {
    const child = spawn(pythonExecutable(root), [script, command], {
      cwd: root,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', chunk => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', chunk => {
      stderr += chunk.toString('utf8');
    });
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) {
        reject(new Error(stderr || stdout || `store command ${command} failed with ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout || '{}') as T);
      }
      catch (error) {
        reject(new Error(`Invalid store response: ${String(error)}\n${stdout}\n${stderr}`));
      }
    });
    child.stdin.end(JSON.stringify({ ...payload, workspaceRoot: root }));
  });
}
