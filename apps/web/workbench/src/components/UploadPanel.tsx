import type { ChangeEvent } from 'react';

interface UploadPanelProps {
  file: File | null;
  onFileChange: (file: File | null) => void;
}

export function UploadPanel({ file, onFileChange }: UploadPanelProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    onFileChange(nextFile);
  };

  return (
    <section className={`panel upload-panel${file ? ' compact' : ''}`}>
      <div className="panel-heading">
        <span className="eyebrow">Source document</span>
        <h2>Load a manuscript</h2>
        <p>The PDF stays in place until you reset the workspace.</p>
      </div>

      {file ? (
        <div className="upload-file-pill">
          <strong>{file.name}</strong>
        </div>
      ) : null}

      <label className="upload-dropzone">
        <input
          type="file"
          accept="application/pdf"
          onChange={handleChange}
          onClick={(event) => {
            event.currentTarget.value = '';
          }}
        />
        <span className="upload-icon" aria-hidden="true">
          PDF
        </span>
        <strong>{file ? 'Replace source PDF' : 'Select a source PDF'}</strong>
        <span>
          {file
            ? 'Click to replace.'
            : 'Drag a manuscript here or click to browse.'}
        </span>
      </label>
    </section>
  );
}
