import { create } from 'zustand';
import type { AccountStatus, Paper, Task } from './types';

type ViewMode = 'library' | 'reader';

type AppState = {
  papers: Paper[];
  selectedId: string;
  tasks: Task[];
  account: AccountStatus;
  viewMode: ViewMode;
  settingsOpen: boolean;
  setPapers: (papers: Paper[]) => void;
  updatePaper: (paper: Paper) => void;
  selectPaper: (id: string) => void;
  setTasks: (tasks: Task[]) => void;
  setAccount: (account: AccountStatus) => void;
  setViewMode: (viewMode: ViewMode) => void;
  setSettingsOpen: (open: boolean) => void;
};

export const useAppStore = create<AppState>((set) => ({
  papers: [],
  selectedId: '',
  tasks: [],
  account: {},
  viewMode: 'library',
  settingsOpen: false,
  setPapers: (papers) => set((state) => ({ papers, selectedId: state.selectedId || papers[0]?.id || '' })),
  updatePaper: (paper) => set((state) => ({ papers: state.papers.map((item) => item.id === paper.id ? paper : item) })),
  selectPaper: (selectedId) => set({ selectedId }),
  setTasks: (tasks) => set({ tasks }),
  setAccount: (account) => set({ account }),
  setViewMode: (viewMode) => set({ viewMode }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen })
}));
