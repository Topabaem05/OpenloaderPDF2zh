export type PreviewTabKey = 'result' | 'boxes' | 'artifacts' | 'details';

interface PreviewTabsProps {
  active: PreviewTabKey;
  onChange: (tab: PreviewTabKey) => void;
}

const tabs: Array<{
  key: PreviewTabKey;
  label: string;
}> = [
  { key: 'result', label: 'Translated PDF' },
  { key: 'boxes', label: 'Detected boxes' },
  { key: 'artifacts', label: 'Artifacts' },
  { key: 'details', label: 'Run details' },
];

export function PreviewTabs({ active, onChange }: PreviewTabsProps) {
  return (
    <div className="preview-tabs" role="tablist" aria-label="Preview tabs">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={active === tab.key}
          className={`preview-tab${active === tab.key ? ' active' : ''}`}
          onClick={() => onChange(tab.key)}
        >
          <strong>{tab.label}</strong>
        </button>
      ))}
    </div>
  );
}
