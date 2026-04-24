import type { JobCreateResponse, JobSettings, JobStatusResponse } from '../types';

const JOB_POLL_INTERVAL_MS = 1500;

function normalizeMessage(value?: string): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function buildStatusCopy(status?: JobStatusResponse | null): string {
  if (!status) {
    return '파일을 업로드하면 작업 상태가 여기에 표시됩니다.';
  }
  const ko = normalizeMessage(status.message_ko);
  const en = normalizeMessage(status.message_en);
  if (ko && en) {
    return `${ko} / ${en}`;
  }
  return ko || en || '작업 정보를 불러오는 중입니다.';
}

export function buildFormData(
  file: File,
  settings: JobSettings,
): FormData {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('provider', settings.provider);
  formData.append('target_language', settings.targetLanguage);
  formData.append('page_mode', settings.pageMode);
  formData.append('render_layout_engine', settings.renderLayoutEngine);
  formData.append(
    'adjust_render_letter_spacing_for_overlap',
    String(settings.adjustLetterSpacing),
  );
  if (settings.openrouterApiKey.trim()) {
    formData.append('openrouter_api_key', settings.openrouterApiKey.trim());
  }
  if (settings.renderFontFile) {
    formData.append('render_font_file', settings.renderFontFile);
  }
  return formData;
}

export async function createJob(
  file: File,
  settings: JobSettings,
): Promise<JobCreateResponse> {
  const response = await fetch('/api/jobs', {
    method: 'POST',
    body: buildFormData(file, settings),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as JobCreateResponse;
}

export async function fetchJobStatus(
  jobId: string,
): Promise<JobStatusResponse> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as JobStatusResponse;
}

async function readErrorMessage(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}`;
  try {
    const text = await response.text();
    if (!text.trim()) {
      return fallback;
    }
    try {
      const payload = JSON.parse(text) as { detail?: string };
      if (typeof payload.detail === 'string' && payload.detail.trim()) {
        return payload.detail.trim();
      }
    } catch {
      // Fall through to plain-text handling.
    }
    return text.trim() || fallback;
  } catch {
    return fallback;
  }
}

export function pollJob(
  jobId: string,
  onUpdate: (status: JobStatusResponse) => void,
  onError: (error: Error) => void,
): () => void {
  let cancelled = false;
  let timer: number | undefined;

  const tick = async () => {
    if (cancelled) {
      return;
    }
    try {
      const status = await fetchJobStatus(jobId);
      onUpdate(status);
      if (
        status.status === 'succeeded' ||
        status.status === 'failed' ||
        status.status === 'queue_busy' ||
        status.status === 'quota_exceeded'
      ) {
        cancelled = true;
        return;
      }
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
      cancelled = true;
      return;
    }
    timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
  };

  void tick();

  return () => {
    cancelled = true;
    if (timer !== undefined) {
      window.clearTimeout(timer);
    }
  };
}
