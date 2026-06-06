/// <reference types="vite/client" />

import type { AccountStatus, Paper, Task } from './types';

type Unsubscribe = () => void;

declare global {
  interface Window {
    scireader: {
      bootstrap: () => Promise<{ service: unknown; papers: Paper[]; config: AccountStatus; root: string }>;
      listPapers: () => Promise<Paper[]>;
      importZotero: (zoteroRoot?: string) => Promise<{ imported: number; papers: Paper[] }>;
      importPdf: () => Promise<{ imported: number; papers: Paper[] }>;
      setStars: (paperId: string, stars: number) => Promise<{ ok: boolean; stars: number }>;
      ingest: (paper: Paper, force?: boolean) => Promise<Record<string, unknown>>;
      metadata: (paper: Paper, force?: boolean) => Promise<Record<string, unknown>>;
      summary: (paper: Paper, force?: boolean) => Promise<{ text?: string; savedPath?: string; cached?: boolean }>;
      readerUrl: (paper: Paper) => Promise<string>;
      assets: (docId: string) => Promise<Record<string, unknown>>;
      chat: (docId: string, question: string) => Promise<{ text: string }>;
      tasks: () => Promise<Task[]>;
      clearDoneTasks: () => Promise<Task[]>;
      onTasks: (callback: (tasks: Task[]) => void) => Unsubscribe;
      getAccount: () => Promise<AccountStatus>;
      updateAccount: (payload: Record<string, string>) => Promise<AccountStatus>;
      updateConfig: (payload: Record<string, string>) => Promise<AccountStatus>;
      syncPush: () => Promise<Record<string, unknown>>;
      syncPull: () => Promise<Record<string, unknown>>;
      openPath: (target: string) => Promise<string>;
      showItem: (target: string) => Promise<void>;
    };
  }
}
