import type { JobSettings } from '../types';

interface JobSettingsPanelProps {
  settings: JobSettings;
  onChange: (next: JobSettings) => void;
}

const providerOptions = [
  { label: 'CTranslate2 / Local', value: 'ctranslate2' },
  { label: 'OpenRouter / Cloud', value: 'groq' },
];

const targetLanguageOptions = [
  { label: 'Korean', value: 'Korean' },
  { label: 'English', value: 'English' },
  { label: 'Japanese', value: 'Japanese' },
  { label: 'Simplified Chinese', value: 'Simplified Chinese' },
  { label: 'Traditional Chinese', value: 'Traditional Chinese' },
];

const pageModeOptions = [
  { label: 'First', value: 'first' },
  { label: 'First 20', value: 'first20' },
  { label: 'All', value: 'all' },
];

const layoutEngineOptions = [
  {
    label: 'Legacy layout',
    value: 'legacy',
    description: 'Keeps the current renderer behavior.',
  },
  {
    label: 'Pretext layout',
    value: 'pretext',
    description: 'Uses the non-overlap renderer.',
  },
];

function updateSettings(
  settings: JobSettings,
  onChange: (next: JobSettings) => void,
  patch: Partial<JobSettings>,
) {
  onChange({ ...settings, ...patch });
}

export function JobSettingsPanel({
  settings,
  onChange,
}: JobSettingsPanelProps) {
  const usesCloudProvider = settings.provider === 'groq';

  return (
    <section className="panel settings-panel">
      <div className="panel-heading">
        <span className="eyebrow">Translation settings</span>
        <h2>Runtime setup</h2>
        <p>Runtime, language, layout.</p>
      </div>

      <div className="field-group">
        <label className="field">
          <span>Runtime</span>
          <select
            value={settings.provider}
            onChange={(event) =>
              updateSettings(settings, onChange, {
                provider: event.target.value,
              })
            }
          >
            {providerOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Language</span>
          <select
            value={settings.targetLanguage}
            onChange={(event) =>
              updateSettings(settings, onChange, {
                targetLanguage: event.target.value,
              })
            }
          >
            {targetLanguageOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Pages</span>
          <select
            value={settings.pageMode}
            onChange={(event) =>
              updateSettings(settings, onChange, {
                pageMode: event.target.value,
              })
            }
          >
            {pageModeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="settings-section">
        <span className="settings-section-title">Layout</span>
        <div className="layout-options">
          {layoutEngineOptions.map((option) => (
            <label
              key={option.value}
              className={`layout-option${settings.renderLayoutEngine === option.value ? ' active' : ''}`}
            >
              <input
                type="radio"
                name="render-layout-engine"
                value={option.value}
                checked={settings.renderLayoutEngine === option.value}
                onChange={(event) =>
                  updateSettings(settings, onChange, {
                    renderLayoutEngine: event.target.value,
                  })
                }
              />
              <div>
                <strong>{option.label}</strong>
                <span>{option.description}</span>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="settings-section">
        <label className="toggle-field">
          <input
            type="checkbox"
            checked={settings.adjustLetterSpacing}
            onChange={(event) =>
              updateSettings(settings, onChange, {
                adjustLetterSpacing: event.target.checked,
              })
            }
          />
          <div>
            <strong>Adjust spacing on overlap</strong>
            <span>Apply extra spacing when render boxes collide.</span>
          </div>
        </label>
      </div>

      <div className="field-group field-group-soft">
        {usesCloudProvider ? (
          <label className="field">
            <span>API key</span>
            <input
              type="password"
              value={settings.openrouterApiKey}
              onChange={(event) =>
                updateSettings(settings, onChange, {
                  openrouterApiKey: event.target.value,
                })
              }
              placeholder="sk-or-v1-..."
            />
          </label>
        ) : null}

        <label className="field">
          <span>Font override</span>
          <input
            type="file"
            accept=".ttf,.ttc,.otf"
            onChange={(event) =>
              updateSettings(settings, onChange, {
                renderFontFile: event.target.files?.[0] ?? null,
              })
            }
          />
        </label>
      </div>
    </section>
  );
}
