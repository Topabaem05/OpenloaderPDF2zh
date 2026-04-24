import type { JobArtifactLinks } from '../types';

interface ArtifactListProps {
  artifacts: JobArtifactLinks | null | undefined;
}

function renderArtifactLink(label: string, description: string, href?: string) {
  if (!href) {
    return null;
  }

  return (
    <a key={label} className="artifact-link" href={href} target="_blank" rel="noreferrer">
      <div className="artifact-link-copy">
        <strong>{label}</strong>
        <span>{description}</span>
      </div>
      <span className="artifact-link-action">Open</span>
    </a>
  );
}

export function ArtifactList({ artifacts }: ArtifactListProps) {
  const links = [
    renderArtifactLink(
      'Translated PDF',
      'Primary rendered output.',
      artifacts?.translated_pdf,
    ),
    renderArtifactLink(
      'Detected boxes PDF',
      'Parser overlay output.',
      artifacts?.detected_boxes_pdf,
    ),
    renderArtifactLink(
      'Structured JSON',
      'Structured parser output.',
      artifacts?.structured_json,
    ),
    renderArtifactLink(
      'Result Markdown',
      'Markdown export.',
      artifacts?.result_md,
    ),
  ].filter(Boolean);

  return (
    <section className="panel">
      <div className="panel-heading">
        <span className="eyebrow">Artifacts</span>
        <h2>Generated files</h2>
        <p>Open the translated output and intermediate files.</p>
      </div>

      <div className="artifact-list">
        {links.length ? (
          links
        ) : (
          <p className="muted-copy">
            Artifact links will appear here after the backend completes the job.
          </p>
        )}
      </div>

      {artifacts?.generated_files?.length ? (
        <div className="artifact-note">
          <span className="detail-label">Workspace files</span>
          <p>{artifacts.generated_files.join(', ')}</p>
        </div>
      ) : null}
    </section>
  );
}
