import { X } from 'lucide-react';
import type { Task } from '../types';

export function TaskDock({ tasks, onClear }: { tasks: Task[]; onClear: () => void }) {
  if (!tasks.length) return null;
  return (
    <aside className="task-dock">
      <div className="task-title">
        <strong>后台任务</strong>
        <button onClick={onClear}><X size={14} /></button>
      </div>
      {tasks.map((task) => (
        <div className="task-card" key={task.id}>
          <div className="task-row">
            <span>{task.title}</span>
            <b>{Math.round(task.progress || 0)}%</b>
          </div>
          <div className="task-stage">{task.stage || task.status}</div>
          <div className="progress-track"><div style={{ width: `${Math.max(4, task.progress || 0)}%` }} /></div>
          {task.error && <div className="task-error">{task.error}</div>}
        </div>
      ))}
    </aside>
  );
}
