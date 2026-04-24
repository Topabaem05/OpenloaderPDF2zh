export type JobStatus =
  | 'idle'
  | 'queued'
  | 'parsing'
  | 'translating'
  | 'rendering'
  | 'succeeded'
  | 'failed'
  | 'quota_exceeded'
  | 'queue_busy';

export type JobStage = JobStatus | 'upload';

export interface QueueSnapshot {
  active?: number;
  waiting?: number;
  capacity?: number;
}

export interface JobArtifactLinks {
  translated_pdf?: string;
  detected_boxes_pdf?: string;
  structured_json?: string;
  result_md?: string;
  generated_files?: string[];
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  stage?: JobStage;
  progress?: number;
  message_ko?: string;
  message_en?: string;
  warnings?: string[];
  queue_snapshot?: QueueSnapshot;
  artifacts?: JobArtifactLinks;
  created_at?: string;
  updated_at?: string;
  error?: string;
}

export interface JobCreateResponse {
  job_id: string;
}

export interface JobSettings {
  provider: string;
  targetLanguage: string;
  pageMode: string;
  renderLayoutEngine: string;
  adjustLetterSpacing: boolean;
  openrouterApiKey: string;
  renderFontFile: File | null;
}

export interface RuntimeSummary {
  title: string;
  subtitle: string;
  badge: string;
}
