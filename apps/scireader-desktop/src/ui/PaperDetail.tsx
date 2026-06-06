import { Bot, Code2, FileText, FolderOpen, ListChecks, MessageSquare, Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import { useState } from 'react';
import { api } from '../api';
import type { Paper } from '../types';

function Badge({ children, tone = 'cold' }: { children: ReactNode; tone?: 'hot' | 'good' | 'mid' | 'cold' }) {
  return <span className={`detail-badge ${tone}`}>{children}</span>;
}

function toneFor(paper: Paper) {
  if (paper.rankScore >= 6) return 'hot';
  if (paper.rankScore >= 4) return 'good';
  if (paper.rankScore >= 2) return 'mid';
  return 'cold';
}

export function PaperDetail({ paper, onRefresh, onRead }: { paper?: Paper; onRefresh: () => Promise<void>; onRead: () => void }) {
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState('');
  if (!paper) {
    return <aside className="detail-pane"><div className="empty-state">选择一篇论文查看详情。</div></aside>;
  }

  async function run(label: string, fn: () => Promise<void>) {
    setLoading(label);
    try {
      await fn();
      await onRefresh();
    }
    finally {
      setLoading('');
    }
  }

  return (
    <aside className="detail-pane">
      <section className="paper-card">
        <div className="eyebrow">Paper Detail</div>
        <h1>{paper.title}</h1>
        <p className="authors">{paper.authors || '作者信息待识别'}</p>
        <div className="detail-badges">
          {paper.venue && <Badge tone={toneFor(paper)}>{paper.venue}</Badge>}
          <Badge tone={toneFor(paper)}>Score {paper.rankScore}</Badge>
          {paper.ccf && <Badge tone={toneFor(paper)}>CCF {paper.ccf}</Badge>}
          {paper.sci && <Badge tone={toneFor(paper)}>{paper.sci}</Badge>}
          {paper.jcr && <Badge tone={toneFor(paper)}>{paper.jcr}</Badge>}
          <Badge>{paper.codeStatus || '开源未知'}</Badge>
        </div>
        <div className="action-grid">
          <button onClick={() => run('后台解析', () => api.ingest(paper, false).then(() => undefined))}><Sparkles size={16} />后台解析</button>
          <button onClick={onRead}><FileText size={16} />重排阅读</button>
          <button onClick={() => run('等级/开源识别', () => api.metadata(paper, true).then(() => undefined))}><ListChecks size={16} />识别等级</button>
          <button onClick={() => run('DeepSeek 摘要', async () => setSummary((await api.summary(paper, false)).text || ''))}><Bot size={16} />AI 总结</button>
        </div>
      </section>

      <section className="paper-card compact">
        <h2>摘要</h2>
        <p className="abstract">{paper.abstract || '暂无摘要。后台解析完成后可生成结构化论文总结。'}</p>
      </section>

      <section className="paper-card compact">
        <h2>附件</h2>
        <div className="file-row">
          <FileText size={16} />
          <span>{paper.pdfPath}</span>
          <button onClick={() => api.showItem(paper.pdfPath)}><FolderOpen size={14} /></button>
        </div>
      </section>

      <section className="paper-card compact">
        <h2>AI Workspace</h2>
        <div className="workspace-shortcuts">
          <div><MessageSquare size={16} /> DeepSeek 问答在阅读视图中使用</div>
          <div><Code2 size={16} /> {paper.codeUrl || paper.codeEvidence || '代码链接待识别'}</div>
        </div>
      </section>

      {summary && (
        <section className="summary-panel">
          <button onClick={() => setSummary('')}>关闭</button>
          <pre>{summary}</pre>
        </section>
      )}
      {loading && <div className="inline-loading">{loading}中...</div>}
    </aside>
  );
}
