interface EmptyStateTilesProps {
  onSampleFocus?: () => void;
}

const tiles = [
  {
    title: 'Upload a manuscript',
    subtitle: 'Bring a source PDF in.',
    tone: 'coral',
    mark: '01',
  },
  {
    title: 'Choose the runtime',
    subtitle: 'Pick engine, language, and scope.',
    tone: 'lavender',
    mark: '02',
  },
  {
    title: 'Start the translation',
    subtitle: 'Follow the pipeline stages.',
    tone: 'sage',
    mark: '03',
  },
  {
    title: 'Review outputs',
    subtitle: 'Open preview and exports.',
    tone: 'butter',
    mark: '04',
  },
];

export function EmptyStateTiles({ onSampleFocus }: EmptyStateTilesProps) {
  return (
    <section className="empty-grid">
      {tiles.map((tile, index) => (
        <button
          key={tile.title}
          className={`empty-tile tone-${tile.tone}`}
          type="button"
          onClick={index === tiles.length - 1 ? onSampleFocus : undefined}
        >
          <span className="empty-tile-subtitle">{tile.subtitle}</span>
          <strong>{tile.title}</strong>
          <span className="empty-tile-mark" aria-hidden="true">
            {tile.mark}
          </span>
        </button>
      ))}
    </section>
  );
}
