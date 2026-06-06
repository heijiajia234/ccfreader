import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { BookOpen, Bot, Cloud, Database, FileDown, FilePlus, Library, RefreshCw, Search, Settings, Sparkles } from 'lucide-react';
import { api } from '../api';
import { useAppStore } from '../store';
import type { Paper } from '../types';
import { PaperTable } from './PaperTable';
import { PaperDetail } from './PaperDetail';
import { ReaderView } from './ReaderView';
import { TaskDock } from './TaskDock';
import { SettingsPanel } from './SettingsPanel';

export function App() {
  const queryClient = useQueryClient();
  const {
    papers,
    selectedId,
    tasks,
    account,
    viewMode,
    settingsOpen,
    setPapers,
    selectPaper,
    setTasks,
    setAccount,
    setViewMode,
    setSettingsOpen
  } = useAppStore();
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState('');
  const selectedPaper = papers.find((paper) => paper.id === selectedId) || papers[0];
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return papers;
    return papers.filter((paper) => [
      paper.title,
      paper.authors,
      paper.venue,
      paper.ccf,
      paper.sci,
      paper.jcr,
      paper.codeStatus
    ].join(' ').toLowerCase().includes(needle));
  }, [papers, search]);

  async function refresh() {
    setPapers(await api.listPapers());
    setAccount(await api.getAccount());
  }

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    try {
      await action();
      await refresh();
      await queryClient.invalidateQueries();
    }
    finally {
      setBusy('');
    }
  }

  useEffect(() => {
    let unsubscribe = () => {};
    api.bootstrap().then((boot) => {
      setPapers(boot.papers || []);
      setAccount(boot.config || {});
    });
    api.tasks().then(setTasks);
    unsubscribe = api.onTasks(setTasks);
    return () => unsubscribe();
  }, [setAccount, setPapers, setTasks]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-title">SciReader</div>
            <div className="brand-subtitle">Local AI research workspace</div>
          </div>
        </div>
        <div className="searchbox">
          <Search size={16} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索标题、作者、期刊、等级、开源状态" />
        </div>
        <div className="toolbar">
          <button onClick={() => run('导入 PDF', () => api.importPdf())}><FilePlus size={16} />导入 PDF</button>
          <button onClick={() => run('读取 Zotero', () => api.importZotero())}><Database size={16} />读取 Zotero</button>
          <button onClick={() => run('云同步', () => api.syncPush())}><Cloud size={16} />云同步</button>
          <button onClick={() => run('云恢复', () => api.syncPull())}><FileDown size={16} />云恢复</button>
          <button onClick={() => setSettingsOpen(true)}><Settings size={16} />设置</button>
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <button className={viewMode === 'library' ? 'nav-item active' : 'nav-item'} onClick={() => setViewMode('library')}><Library size={17} />文献库</button>
          <button className={viewMode === 'reader' ? 'nav-item active' : 'nav-item'} onClick={() => setViewMode('reader')}><BookOpen size={17} />重排阅读</button>
          <div className="sidebar-section">研究流</div>
          <button className="nav-item muted"><Sparkles size={17} />分类推荐</button>
          <button className="nav-item muted"><Bot size={17} />科研 Skill</button>
          <div className="account-card">
            <div className="sidebar-section">账户</div>
            <div className="mini-line">{account.accountConfigured ? '已登录' : '未登录'}</div>
            <div className="mini-muted">{account.accountName || account.webdavUser || '配置 WebDAV 后同步'}</div>
            <div className="mini-status">
              <span className={account.deepseekConfigured ? 'dot ok' : 'dot'} />
              DeepSeek
              <span className={account.easyScholarConfigured ? 'dot ok' : 'dot'} />
              EasyScholar
            </div>
          </div>
        </aside>

        {viewMode === 'library' ? (
          <>
            <section className="list-pane">
              <div className="pane-header">
                <div>
                  <h2>论文库</h2>
                  <p>{filtered.length} / {papers.length} 篇论文，支持等级、重要性、开源状态排序</p>
                </div>
                <button className="ghost" onClick={() => run('刷新', refresh)}><RefreshCw size={15} />刷新</button>
              </div>
              <PaperTable papers={filtered} selectedId={selectedPaper?.id || ''} onSelect={(paper: Paper) => selectPaper(paper.id)} />
            </section>
            <PaperDetail paper={selectedPaper} onRefresh={refresh} onRead={() => setViewMode('reader')} />
          </>
        ) : (
          <ReaderView paper={selectedPaper} onBack={() => setViewMode('library')} onRefresh={refresh} />
        )}
      </main>

      {busy && <div className="busy-toast">{busy}处理中...</div>}
      <TaskDock tasks={tasks} onClear={async () => setTasks(await api.clearDoneTasks())} />
      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} onSaved={refresh} />}
    </div>
  );
}
