import { ArrowLeft, Bot, Images, RefreshCw, Send, Table2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';
import type { AssetPayload, Paper } from '../types';

export function ReaderView({ paper, onBack, onRefresh }: { paper?: Paper; onBack: () => void; onRefresh: () => Promise<void> }) {
  const [url, setUrl] = useState('');
  const [assets, setAssets] = useState<AssetPayload>({});
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState('');

  useEffect(() => {
    if (!paper) return;
    api.readerUrl(paper).then(setUrl);
    if (paper.docId) {
      api.assets(paper.docId).then((data) => setAssets(data as AssetPayload)).catch(() => setAssets({}));
    }
  }, [paper]);

  if (!paper) {
    return <section className="reader-empty"><button onClick={onBack}>返回</button>请选择一篇论文。</section>;
  }
  const activePaper = paper;

  async function parse() {
    setBusy('后台解析');
    try {
      await api.ingest(activePaper, false);
      await onRefresh();
    }
    finally {
      setBusy('');
    }
  }

  async function ask() {
    if (!activePaper.docId || !question.trim()) return;
    setBusy('DeepSeek 回答');
    try {
      const result = await api.chat(activePaper.docId, question);
      setAnswer(result.text || '');
    }
    finally {
      setBusy('');
    }
  }

  return (
    <section className="reader-layout">
      <div className="reader-main">
        <div className="reader-toolbar">
          <button onClick={onBack}><ArrowLeft size={16} />返回文献库</button>
          <strong>{paper.title}</strong>
          <button onClick={parse}><RefreshCw size={16} />后台解析</button>
        </div>
        {url ? <iframe className="reader-frame" src={url} /> : <div className="empty-state">正在加载阅读器...</div>}
      </div>
      <aside className="reader-side">
        <section className="paper-card compact">
          <h2><Bot size={16} /> DeepSeek 论文问答</h2>
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="询问这篇文章的方法、实验、局限或公式含义" />
          <button className="primary-wide" onClick={ask}><Send size={15} />提问</button>
          {answer && <pre className="answer-box">{answer}</pre>}
        </section>
        <section className="paper-card compact asset-list">
          <h2><Images size={16} /> 图像</h2>
          {(assets.figures || []).slice(0, 6).map((figure, index) => (
            <div className="asset-item" key={`f-${index}`}>{String(figure.caption || figure.label || `Figure ${index + 1}`)}</div>
          ))}
          {!(assets.figures || []).length && <div className="mini-muted">解析完成后显示论文图片。</div>}
        </section>
        <section className="paper-card compact asset-list">
          <h2><Table2 size={16} /> 表格</h2>
          {(assets.tables || []).slice(0, 6).map((table, index) => (
            <div className="asset-item" key={`t-${index}`}>{String(table.caption || table.label || `Table ${index + 1}`)}</div>
          ))}
          {!(assets.tables || []).length && <div className="mini-muted">解析完成后显示实验表格。</div>}
        </section>
        {busy && <div className="inline-loading">{busy}中...</div>}
      </aside>
    </section>
  );
}
