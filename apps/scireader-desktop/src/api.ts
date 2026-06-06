import type { AccountStatus, Paper, Task } from './types';

export const api = {
  bootstrap: () => window.scireader.bootstrap(),
  listPapers: () => window.scireader.listPapers(),
  importZotero: (zoteroRoot?: string) => window.scireader.importZotero(zoteroRoot),
  importPdf: () => window.scireader.importPdf(),
  setStars: (paperId: string, stars: number) => window.scireader.setStars(paperId, stars),
  ingest: (paper: Paper, force = false) => window.scireader.ingest(paper, force),
  metadata: (paper: Paper, force = false) => window.scireader.metadata(paper, force),
  summary: (paper: Paper, force = false) => window.scireader.summary(paper, force),
  readerUrl: (paper: Paper) => window.scireader.readerUrl(paper),
  assets: (docId: string) => window.scireader.assets(docId),
  chat: (docId: string, question: string) => window.scireader.chat(docId, question),
  tasks: () => window.scireader.tasks(),
  clearDoneTasks: () => window.scireader.clearDoneTasks(),
  onTasks: (callback: (tasks: Task[]) => void) => window.scireader.onTasks(callback),
  getAccount: () => window.scireader.getAccount(),
  updateAccount: (payload: Record<string, string>): Promise<AccountStatus> => window.scireader.updateAccount(payload),
  updateConfig: (payload: Record<string, string>): Promise<AccountStatus> => window.scireader.updateConfig(payload),
  syncPush: () => window.scireader.syncPush(),
  syncPull: () => window.scireader.syncPull(),
  openPath: (target: string) => window.scireader.openPath(target),
  showItem: (target: string) => window.scireader.showItem(target)
};
