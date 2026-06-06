export type Paper = {
  id: string;
  title: string;
  authors: string;
  year: string;
  venue: string;
  ccf: string;
  sci: string;
  jcr: string;
  rankScore: number;
  codeStatus: string;
  codeUrl: string;
  codeEvidence: string;
  importance: number;
  abstract: string;
  pdfPath: string;
  docId: string;
  source: string;
  zoteroItemId: string;
  status: string;
  stage: string;
  progress: number;
  error: string;
  summaryPath: string;
  updatedAt: number;
};

export type Task = {
  id: string;
  paperId: string;
  title: string;
  status: string;
  stage: string;
  progress: number;
  error?: string;
  updated: number;
};

export type AccountStatus = {
  deepseekConfigured?: boolean;
  easyScholarConfigured?: boolean;
  webdavConfigured?: boolean;
  accountConfigured?: boolean;
  webdavUrl?: string;
  webdavUser?: string;
  accountName?: string;
  deepseekModel?: string;
};

export type AssetPayload = {
  figures?: Array<Record<string, string | number>>;
  tables?: Array<Record<string, string | number>>;
};
