import type { ReactNode } from 'react';

interface PdfPreviewPaneProps {
  title: string;
  subtitle: string;
  src?: string;
  fallback: ReactNode;
}

export function PdfPreviewPane({
  title,
  subtitle,
  src,
  fallback,
}: PdfPreviewPaneProps) {
  return (
    <section className="panel preview-panel">
      <div className="preview-panel-header">
        <div className="panel-heading">
          <span className="eyebrow">{subtitle}</span>
          <h2>{title}</h2>
        </div>
        <span className="preview-badge">{src ? 'Preview' : 'Waiting'}</span>
      </div>

      <div className="preview-surface">
        <div className="preview-toolbar" aria-hidden="true">
          <span>Viewer</span>
          <span>{subtitle}</span>
          <span>{src ? 'Live' : 'Placeholder'}</span>
        </div>

        {src ? (
          <div className="preview-frame">
            <iframe title={title} src={src} />
          </div>
        ) : (
          <div className="empty-panel">{fallback}</div>
        )}
      </div>
    </section>
  );
}
