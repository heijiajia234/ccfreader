import { contextBridge, ipcRenderer } from 'electron';

const api = {
  bootstrap: () => ipcRenderer.invoke('app:bootstrap'),
  listPapers: () => ipcRenderer.invoke('papers:list'),
  importZotero: (zoteroRoot?: string) => ipcRenderer.invoke('papers:importZotero', zoteroRoot),
  importPdf: () => ipcRenderer.invoke('papers:importPdf'),
  setStars: (paperId: string, stars: number) => ipcRenderer.invoke('papers:setStars', paperId, stars),
  ingest: (paper: unknown, force = false) => ipcRenderer.invoke('papers:ingest', paper, force),
  metadata: (paper: unknown, force = false) => ipcRenderer.invoke('papers:metadata', paper, force),
  summary: (paper: unknown, force = false) => ipcRenderer.invoke('papers:summary', paper, force),
  readerUrl: (paper: unknown) => ipcRenderer.invoke('reader:url', paper),
  assets: (docId: string) => ipcRenderer.invoke('reader:assets', docId),
  chat: (docId: string, question: string) => ipcRenderer.invoke('reader:chat', docId, question),
  tasks: () => ipcRenderer.invoke('tasks:list'),
  clearDoneTasks: () => ipcRenderer.invoke('tasks:clearDone'),
  onTasks: (callback: (tasks: unknown[]) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, tasks: unknown[]) => callback(tasks);
    ipcRenderer.on('tasks:update', listener);
    return () => ipcRenderer.removeListener('tasks:update', listener);
  },
  getAccount: () => ipcRenderer.invoke('account:get'),
  updateAccount: (payload: unknown) => ipcRenderer.invoke('account:update', payload),
  updateConfig: (payload: unknown) => ipcRenderer.invoke('config:update', payload),
  syncPush: () => ipcRenderer.invoke('sync:push'),
  syncPull: () => ipcRenderer.invoke('sync:pull'),
  openPath: (target: string) => ipcRenderer.invoke('shell:openPath', target),
  showItem: (target: string) => ipcRenderer.invoke('shell:showItem', target)
};

contextBridge.exposeInMainWorld('scireader', api);
