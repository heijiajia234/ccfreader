import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
import path from 'node:path';
import { ensureReflowService, REFLOW_BASE_URL, stopReflowService, workspaceRoot } from './service-manager';
import { runStoreCommand } from './store-bridge';

type Paper = {
  id: string;
  title: string;
  authors?: string;
  venue?: string;
  pdfPath: string;
  docId?: string;
};

type Task = {
  id: string;
  paperId: string;
  title: string;
  status: string;
  stage: string;
  progress: number;
  error?: string;
  updated: number;
};

let mainWindow: BrowserWindow | null = null;
let root = '';
const tasks = new Map<string, Task>();

function serviceURL(endpoint: string, params: Record<string, string | number | boolean | undefined> = {}) {
  const url = new URL(endpoint, REFLOW_BASE_URL);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function getJSON<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

async function postJSON<T>(endpoint: string, body: unknown): Promise<T> {
  const response = await fetch(`${REFLOW_BASE_URL}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

function pushTasks() {
  mainWindow?.webContents.send('tasks:update', Array.from(tasks.values()));
}

async function pollTask(taskId: string, paper: Paper) {
  const task = tasks.get(taskId);
  if (!task) return;
  try {
    const status = await getJSON<Record<string, any>>(serviceURL('/api/status', { id: taskId }));
    task.status = status.status || 'running';
    task.stage = status.stage || task.status;
    task.progress = Number(status.progress || 0);
    task.error = status.error || '';
    task.updated = Date.now();
    await runStoreCommand(root, 'update_status', {
      paperId: paper.id,
      docId: taskId,
      status: task.status,
      stage: task.stage,
      progress: task.progress,
      error: task.error
    });
    pushTasks();
    if (task.status === 'ready') {
      const meta = await getJSON<Record<string, any>>(serviceURL('/api/metadata', { id: taskId }));
      await runStoreCommand(root, 'update_metadata', { paperId: paper.id, docId: taskId, metadata: meta });
      pushTasks();
      return;
    }
    if (task.status === 'error') {
      pushTasks();
      return;
    }
  }
  catch (error) {
    task.status = 'error';
    task.stage = 'error';
    task.error = String(error);
    pushTasks();
    return;
  }
  setTimeout(() => pollTask(taskId, paper), 1400);
}

async function ingestPaper(paper: Paper, force = false) {
  const result = await getJSON<Record<string, any>>(serviceURL('/api/ingest', {
    path: paper.pdfPath,
    title: paper.title,
    venue: paper.venue || '',
    itemID: paper.id,
    translate: 1,
    force: force ? 1 : 0
  }));
  const docId = String(result.id || paper.docId || '');
  if (!docId) {
    throw new Error('reflow-service did not return a document id');
  }
  tasks.set(docId, {
    id: docId,
    paperId: paper.id,
    title: paper.title,
    status: result.status || 'queued',
    stage: result.stage || 'queued',
    progress: Number(result.progress || 0),
    error: result.error || '',
    updated: Date.now()
  });
  await runStoreCommand(root, 'update_status', {
    paperId: paper.id,
    docId,
    status: result.status || 'queued',
    stage: result.stage || 'queued',
    progress: Number(result.progress || 0),
    error: result.error || ''
  });
  pushTasks();
  pollTask(docId, { ...paper, docId });
  return { id: docId, ...result };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    show: false,
    backgroundColor: '#f6f8fb',
    title: 'SciReader',
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false
    }
  });
  mainWindow.once('ready-to-show', () => {
    mainWindow?.maximize();
    mainWindow?.show();
  });
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  }
  else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  }
}

function registerIPC() {
  ipcMain.handle('app:bootstrap', async () => {
    const service = await ensureReflowService(root);
    await runStoreCommand(root, 'init');
    const papers = await runStoreCommand(root, 'list');
    const config = await getJSON<Record<string, any>>(`${REFLOW_BASE_URL}/api/config`).catch(() => ({}));
    return { service, papers, config, root };
  });
  ipcMain.handle('papers:list', () => runStoreCommand(root, 'list'));
  ipcMain.handle('papers:importZotero', (_event, zoteroRoot?: string) => runStoreCommand(root, 'import_zotero', { zoteroRoot }));
  ipcMain.handle('papers:importPdf', async () => {
    const result = await dialog.showOpenDialog(mainWindow!, {
      title: '导入 PDF',
      properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'PDF', extensions: ['pdf'] }]
    });
    if (result.canceled || !result.filePaths.length) {
      return { imported: 0, papers: [] };
    }
    return runStoreCommand(root, 'upsert_pdfs', { paths: result.filePaths, copy: true });
  });
  ipcMain.handle('papers:setStars', (_event, paperId: string, stars: number) => runStoreCommand(root, 'set_stars', { paperId, stars }));
  ipcMain.handle('papers:ingest', async (_event, paper: Paper, force?: boolean) => ingestPaper(paper, !!force));
  ipcMain.handle('papers:metadata', async (_event, paper: Paper, force?: boolean) => {
    const docId = paper.docId || (await ingestPaper(paper, false)).id;
    const meta = await getJSON<Record<string, any>>(serviceURL('/api/metadata', { id: docId, force: force ? 1 : 0 }));
    await runStoreCommand(root, 'update_metadata', { paperId: paper.id, docId, metadata: meta });
    return meta;
  });
  ipcMain.handle('papers:summary', async (_event, paper: Paper, force?: boolean) => {
    const docId = paper.docId || (await ingestPaper(paper, false)).id;
    return getJSON(serviceURL('/api/summary', { id: docId, force: force ? 1 : 0 }));
  });
  ipcMain.handle('reader:url', (_event, paper: Paper) => serviceURL('/reflow', {
    path: paper.pdfPath,
    title: paper.title,
    venue: paper.venue || '',
    itemID: paper.id
  }));
  ipcMain.handle('reader:assets', async (_event, docId: string) => getJSON(serviceURL('/api/assets', { id: docId })));
  ipcMain.handle('reader:chat', async (_event, docId: string, question: string) => postJSON('/api/chat', { id: docId, question }));
  ipcMain.handle('tasks:list', () => Array.from(tasks.values()));
  ipcMain.handle('tasks:clearDone', () => {
    for (const [id, task] of tasks.entries()) {
      if (task.status === 'ready' || task.status === 'error') tasks.delete(id);
    }
    pushTasks();
    return Array.from(tasks.values());
  });
  ipcMain.handle('account:get', () => getJSON(`${REFLOW_BASE_URL}/api/account`));
  ipcMain.handle('account:update', (_event, payload) => postJSON('/api/account', payload));
  ipcMain.handle('config:update', (_event, payload) => postJSON('/api/config', payload));
  ipcMain.handle('sync:push', async () => {
    const items = await runStoreCommand<Array<{ path: string; title: string }>>(root, 'sync_items');
    return postJSON('/api/sync', { items });
  });
  ipcMain.handle('sync:pull', async () => {
    const pulled = await postJSON<Record<string, any>>('/api/sync/pull', {});
    const documents = Array.isArray(pulled.documents) ? pulled.documents : [];
    const paths = documents.map((doc: any) => doc.pdfPath).filter(Boolean);
    if (paths.length) {
      await runStoreCommand(root, 'upsert_pdfs', { paths, copy: false, source: 'webdav' });
    }
    return pulled;
  });
  ipcMain.handle('shell:openPath', (_event, target: string) => shell.openPath(target));
  ipcMain.handle('shell:showItem', (_event, target: string) => shell.showItemInFolder(target));
}

app.whenReady().then(async () => {
  root = workspaceRoot(app.getAppPath());
  registerIPC();
  createWindow();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  stopReflowService();
});
