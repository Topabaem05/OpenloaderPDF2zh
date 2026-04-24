import type { CSSProperties } from 'react';
import type { JobStatusResponse } from '../types';

interface RunStatusStripProps {
  status: JobStatusResponse | null;
}

const stageLabels = [
  { key: 'upload', label: 'Upload' },
  { key: 'parsing', label: 'Parse' },
  { key: 'translating', label: 'Translate' },
  { key: 'rendering', label: 'Render' },
];

const statusCopy: Record<string, { title: string; description: string; badge: string }> = {
  idle: {
    title: 'Awaiting a source document',
    description: 'Choose a PDF to begin.',
    badge: 'Ready',
  },
  queued: {
    title: 'Queued for processing',
    description: 'The backend accepted the job.',
    badge: 'Queued',
  },
  parsing: {
    title: 'Parsing page structure',
    description: 'The parser is mapping layout blocks.',
    badge: 'Parsing',
  },
  translating: {
    title: 'Translating extracted content',
    description: 'The provider is translating extracted units.',
    badge: 'Translating',
  },
  rendering: {
    title: 'Rendering translated output',
    description: 'The PDF is being rebuilt.',
    badge: 'Rendering',
  },
  succeeded: {
    title: 'Translation complete',
    description: 'Preview the PDF or inspect artifacts.',
    badge: 'Complete',
  },
  failed: {
    title: 'Translation failed',
    description: 'Review the error state and retry.',
    badge: 'Failed',
  },
  quota_exceeded: {
    title: 'Quota exceeded',
    description: 'The runtime quota is exhausted.',
    badge: 'Quota',
  },
  queue_busy: {
    title: 'Queue is currently full',
    description: 'Retry when capacity becomes available.',
    badge: 'Busy',
  },
};

export function RunStatusStrip({ status }: RunStatusStripProps) {
  const progress = Math.min(Math.max(status?.progress ?? 0, 0), 1);
  const currentStage = status?.stage ?? 'upload';
  const warningCount = status?.warnings?.length ?? 0;
  const queueText = status?.queue_snapshot
    ? `${status.queue_snapshot.active ?? 0} active / ${status.queue_snapshot.waiting ?? 0} waiting`
    : 'Visible after job acceptance.';
  const copy = status ? statusCopy[status.status] ?? statusCopy.idle : statusCopy.idle;
  const ringStyle = {
    '--progress-angle': `${progress * 360}deg`,
  } as CSSProperties;
  const stageKey =
    currentStage === 'queued' ||
    currentStage === 'failed' ||
    currentStage === 'quota_exceeded' ||
    currentStage === 'queue_busy' ||
    currentStage === 'succeeded'
      ? currentStage === 'succeeded'
        ? 'rendering'
        : currentStage === 'queued'
          ? 'upload'
          : status?.stage === 'rendering'
            ? 'rendering'
            : currentStage
      : currentStage;
  const activeIndex = stageLabels.findIndex((stage) => stage.key === stageKey);

  return (
    <section className="panel status-strip">
      <div className="status-overview">
        <div className="status-copy">
          <span className="eyebrow">Current progress</span>
          <h2>{copy.title}</h2>
          <p>{status?.message_en?.trim() || copy.description}</p>
        </div>

        <div
          className="status-ring"
          style={ringStyle}
          aria-label={`Progress ${Math.round(progress * 100)} percent`}
        >
          <div className="status-ring-inner">
            <strong>{Math.round(progress * 100)}%</strong>
            <span>{copy.badge}</span>
          </div>
        </div>
      </div>

      <div className="status-track" aria-label="Pipeline stages">
        {stageLabels.map((stage, index) => {
          const active = activeIndex >= 0 && index === activeIndex;
          const complete = activeIndex > index || status?.status === 'succeeded';

          return (
            <div
              key={stage.key}
              className={`status-step${active ? ' active' : ''}${complete ? ' complete' : ''}`}
            >
              <span className="status-step-index">{String(index + 1).padStart(2, '0')}</span>
              <strong>{stage.label}</strong>
            </div>
          );
        })}
      </div>

      <div className="status-meta">
        <div className="status-meta-card">
          <span className="detail-label">Warnings</span>
          <strong>{warningCount}</strong>
        </div>
        <div className="status-meta-card">
          <span className="detail-label">Queue snapshot</span>
          <strong>{queueText}</strong>
        </div>
        <div className="status-meta-card">
          <span className="detail-label">Job status</span>
          <strong>{copy.badge}</strong>
        </div>
      </div>
    </section>
  );
}
