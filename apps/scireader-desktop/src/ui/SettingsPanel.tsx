import { useEffect, useState } from 'react';
import { api } from '../api';
import type { AccountStatus } from '../types';

export function SettingsPanel({ onClose, onSaved }: { onClose: () => void; onSaved: () => Promise<void> }) {
  const [status, setStatus] = useState<AccountStatus>({});
  const [form, setForm] = useState({
    accountName: '',
    webdavUrl: 'https://dav.jianguoyun.com/dav/',
    webdavUser: '',
    webdavPassword: '',
    deepseekKey: '',
    easyScholarKey: '',
    deepseekModel: 'deepseek-chat'
  });
  const [message, setMessage] = useState('');

  useEffect(() => {
    api.getAccount().then((next) => {
      setStatus(next);
      setForm((old) => ({
        ...old,
        accountName: next.accountName || '',
        webdavUrl: next.webdavUrl || old.webdavUrl,
        webdavUser: next.webdavUser || '',
        deepseekModel: next.deepseekModel || old.deepseekModel
      }));
    });
  }, []);

  async function saveConfig() {
    const next = await api.updateConfig(form);
    setStatus(next);
    setMessage('接口配置已保存');
    await onSaved();
  }

  async function login() {
    const next = await api.updateAccount(form);
    setStatus(next);
    setMessage('账户已连接，云端 account.json 已更新');
    await onSaved();
  }

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((old) => ({ ...old, [key]: value }));
  }

  return (
    <div className="modal-backdrop">
      <section className="settings-modal">
        <div className="modal-header">
          <div>
            <h2>SciReader 设置</h2>
            <p>密钥只写入本地 `reflow-cache/config.json`，前端不会显示已保存密钥。</p>
          </div>
          <button onClick={onClose}>关闭</button>
        </div>
        <div className="settings-grid">
          <label>账户名称<input value={form.accountName} onChange={(event) => set('accountName', event.target.value)} /></label>
          <label>WebDAV 地址<input value={form.webdavUrl} onChange={(event) => set('webdavUrl', event.target.value)} /></label>
          <label>WebDAV 账号<input value={form.webdavUser} onChange={(event) => set('webdavUser', event.target.value)} /></label>
          <label>WebDAV 应用密码<input type="password" value={form.webdavPassword} onChange={(event) => set('webdavPassword', event.target.value)} placeholder="留空则不修改" /></label>
          <label>DeepSeek Key<input type="password" value={form.deepseekKey} onChange={(event) => set('deepseekKey', event.target.value)} placeholder="留空则不修改" /></label>
          <label>DeepSeek 模型<input value={form.deepseekModel} onChange={(event) => set('deepseekModel', event.target.value)} /></label>
          <label>EasyScholar SecretKey<input type="password" value={form.easyScholarKey} onChange={(event) => set('easyScholarKey', event.target.value)} placeholder="留空则不修改" /></label>
        </div>
        <div className="settings-status">
          <span className={status.deepseekConfigured ? 'pill ok' : 'pill'}>DeepSeek {status.deepseekConfigured ? '已配置' : '未配置'}</span>
          <span className={status.easyScholarConfigured ? 'pill ok' : 'pill'}>EasyScholar {status.easyScholarConfigured ? '已配置' : '未配置'}</span>
          <span className={status.webdavConfigured ? 'pill ok' : 'pill'}>WebDAV {status.webdavConfigured ? '已配置' : '未配置'}</span>
        </div>
        <div className="modal-actions">
          <button onClick={saveConfig}>保存接口配置</button>
          <button className="primary-wide" onClick={login}>注册/登录并写入云端</button>
        </div>
        {message && <div className="success-line">{message}</div>}
      </section>
    </div>
  );
}
