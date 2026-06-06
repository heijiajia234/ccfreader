import { useMemo } from 'react';
import { ColumnDef, flexRender, getCoreRowModel, getSortedRowModel, SortingState, useReactTable } from '@tanstack/react-table';
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { api } from '../api';
import { useAppStore } from '../store';
import type { Paper } from '../types';

function rankLabel(paper: Paper) {
  const parts = [paper.ccf && `CCF ${paper.ccf}`, paper.sci, paper.jcr].filter(Boolean);
  return parts.length ? parts.join(' / ') : '未知';
}

function rankClass(score: number) {
  if (score >= 6) return 'rank hot';
  if (score >= 4) return 'rank good';
  if (score >= 2) return 'rank mid';
  return 'rank cold';
}

function Stars({ paper }: { paper: Paper }) {
  const setPapers = useAppStore((state) => state.setPapers);
  return (
    <div className="stars-cell" onClick={(event) => event.stopPropagation()}>
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          title={`${star} 星，Ctrl+点击清零`}
          onClick={async (event) => {
            await api.setStars(paper.id, event.ctrlKey ? 0 : star);
            setPapers(await api.listPapers());
          }}
        >
          {star <= paper.importance ? '★' : '☆'}
        </button>
      ))}
    </div>
  );
}

export function PaperTable({ papers, selectedId, onSelect }: { papers: Paper[]; selectedId: string; onSelect: (paper: Paper) => void }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'rankScore', desc: true }]);
  const columns = useMemo<ColumnDef<Paper>[]>(() => [
    {
      accessorKey: 'title',
      header: '标题',
      cell: ({ row }) => (
        <div className="title-cell">
          <strong>{row.original.title}</strong>
          <span>{row.original.authors || '作者未知'}{row.original.year ? ` · ${row.original.year}` : ''}</span>
        </div>
      )
    },
    {
      accessorKey: 'venue',
      header: '期刊/会议',
      cell: ({ row }) => row.original.venue || '未知'
    },
    {
      accessorKey: 'rankScore',
      header: '等级',
      cell: ({ row }) => <span className={rankClass(row.original.rankScore)}>{rankLabel(row.original)}</span>
    },
    {
      accessorKey: 'codeStatus',
      header: '开源',
      cell: ({ row }) => (
        <span className={row.original.codeStatus?.includes('开源') || row.original.codeUrl ? 'code open' : 'code'}>
          {row.original.codeStatus || '未知'}
          {row.original.codeUrl ? <ExternalLink size={12} /> : null}
        </span>
      )
    },
    {
      accessorKey: 'importance',
      header: '重要性',
      cell: ({ row }) => <Stars paper={row.original} />
    },
    {
      accessorKey: 'status',
      header: '解析',
      cell: ({ row }) => <span className={`status ${row.original.status || 'idle'}`}>{row.original.status || '未解析'}</span>
    }
  ], []);
  const table = useReactTable({
    data: papers,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel()
  });
  return (
    <div className="table-wrap">
      <table>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} onClick={header.column.getToggleSortingHandler()}>
                  {flexRender(header.column.columnDef.header, header.getContext())}
                  <span className="sort-mark">{header.column.getIsSorted() === 'asc' ? '↑' : header.column.getIsSorted() === 'desc' ? '↓' : ''}</span>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className={row.original.id === selectedId ? 'selected' : ''} onClick={() => onSelect(row.original)}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!papers.length && <div className="empty-state">还没有论文。先导入 PDF 或读取 Zotero storage。</div>}
    </div>
  );
}
