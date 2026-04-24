import {
  lazy,
  startTransition,
  Suspense,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  WorkbenchShell,
  type NavigationItemId,
} from './components/WorkbenchShell';
import { createJob, pollJob } from './lib/api';
import type { JobSettings, JobStatusResponse } from './types';

const preloadPdfCanvasPreview = () => import('./components/PdfCanvasPreview');
const PdfCanvasPreview = lazy(preloadPdfCanvasPreview);

type SourceLanguage = 'Latin' | 'Ancient Greek' | 'English' | 'Korean';
type Specialization = 'academic' | 'legal' | 'general';
type OverlayPanel = 'guidelines' | 'library' | 'archives' | 'notifications' | 'account';

const TOTAL_PAGES = 42;
const MIN_ZOOM = 85;
const MAX_ZOOM = 135;
const ZOOM_STEP = 10;

const defaultSettings: JobSettings = {
  provider: 'ctranslate2',
  targetLanguage: 'English',
  pageMode: 'first',
  renderLayoutEngine: 'legacy',
  adjustLetterSpacing: true,
  openrouterApiKey: '',
  renderFontFile: null,
};

const sourceLanguageOptions: Array<{ value: SourceLanguage; label: string }> = [
  { value: 'Latin', label: 'Latin (Classical)' },
  { value: 'Ancient Greek', label: 'Ancient Greek' },
  { value: 'English', label: 'English (Modern)' },
  { value: 'Korean', label: 'Korean (Modern)' },
];

const targetLanguageOptions: Array<{ value: SourceLanguage; label: string }> = [
  { value: 'English', label: 'English (Scholarly)' },
  { value: 'Korean', label: 'Korean (Modern)' },
  { value: 'Latin', label: 'Latin (Scholarly)' },
  { value: 'Ancient Greek', label: 'Ancient Greek' },
];

const specializationOptions: Array<{
  value: Specialization;
  title: string;
  description: string;
}> = [
  {
    value: 'academic',
    title: 'Academic',
    description: 'Nuanced, literal, maintains syntax.',
  },
  {
    value: 'legal',
    title: 'Legal',
    description: 'Terminology-dense, formal structure.',
  },
  {
    value: 'general',
    title: 'General',
    description: 'Natural flow, modern vocabulary.',
  },
];

const manuscriptPages = [
  [
    'Gallia est omnis divisa in partes tres, quarum unam incolunt Belgae, aliam Aquitani, tertiam qui ipsorum lingua Celtae, nostra Galli appellantur.',
    'Hi omnes lingua, institutis, legibus inter se differunt. Garumna flumen Aquitanos a Gallis, Matrona et Sequana Belgas a Gallis dividit.',
    'Horum omnium fortissimi sunt Belgae, propterea quod a cultu atque humanitate provinciae longissime absunt.',
    'Qua de causa Helvetii quoque reliquos Gallos virtute praecedunt, quod fere cotidianis proeliis cum Germanis contendunt.',
    'Cum aut suis finibus eos prohibent aut ipsi in eorum finibus bellum gerunt. Eorum una pars, quam Gallos obtinere dictum est, initium capit a flumine Rhodano.',
    'Continetur Garumna flumine, Oceano, finibus Belgarum, attingit etiam ab Sequanis et Helvetiis flumen Rhenum, vergit ad septentriones.',
    'Belgae ab extremis Galliae finibus oriuntur, pertinent ad inferiorem partem fluminis Rheni, spectant in septentrionem et orientem solem.',
  ],
  [
    'Apud Helvetios longe nobilissimus fuit et ditissimus Orgetorix. Is, M. Messala et M. Pisone consulibus, regni cupiditate inductus coniurationem nobilitatis fecit.',
    'Civitati persuasit ut de finibus suis cum omnibus copiis exirent: perfacile esse, cum virtute omnibus praestarent, totius Galliae imperio potiri.',
    'Id hoc facilius eis persuasit, quod undique loci natura Helvetii continentur: una ex parte flumine Rheno latissimo atque altissimo.',
    'Altera ex parte monte Iura altissimo, qui est inter Sequanos et Helvetios, tertia lacu Lemanno et flumine Rhodano, qui provinciam nostram ab Helvetiis dividit.',
    'His rebus fiebat ut et minus late vagarentur et minus facile finitimis bellum inferre possent; qua ex parte homines bellandi cupidi magno dolore adficiebantur.',
    'Pro multitudine autem hominum et pro gloria belli atque fortitudinis angustos se fines habere arbitrabantur.',
  ],
  [
    'His rebus adducti et auctoritate Orgetorigis permoti constituerunt ea quae ad proficiscendum pertinerent comparare, iumentorum et carrorum quam maximum numerum coemere.',
    'Sementes quam maximas facere, ut in itinere copia frumenti suppeteret, cum proximis civitatibus pacem et amicitiam confirmare.',
    'Ad eas res conficiendas biennium sibi satis esse duxerunt; in tertium annum profectionem lege confirmant.',
    'Ad eas res conficiendas Orgetorix deligitur. Is sibi legationem ad civitates suscipit.',
    'In eo itinere persuadet Castico Catamantaloedis filio Sequano, cuius pater regnum in Sequanis multos annos obtinuerat, ut regnum in civitate sua occuparet.',
    'Item Dumnorigi Haeduo persuadet ut idem conaretur, eique filiam suam in matrimonium dat.',
  ],
];

const activeStatuses = new Set(['queued', 'parsing', 'translating', 'rendering']);
const retryableStatuses = new Set(['failed', 'queue_busy', 'quota_exceeded']);

function mapStatusLabel(status: JobStatusResponse | null): string {
  if (!status) {
    return 'Ready';
  }
  switch (status.status) {
    case 'queued':
      return 'Queued';
    case 'parsing':
      return 'Parsing';
    case 'translating':
      return 'Translating';
    case 'rendering':
      return 'Rendering';
    case 'succeeded':
      return 'Complete';
    case 'failed':
      return 'Failed';
    case 'quota_exceeded':
      return 'Quota';
    case 'queue_busy':
      return 'Busy';
    default:
      return 'Ready';
  }
}

function mapStatusCopy(status: JobStatusResponse | null, file: File | null): string {
  if (!file) {
    return 'Select a source PDF to begin.';
  }
  if (!status) {
    return 'The manuscript is loaded and ready for translation.';
  }
  if (status.message_en?.trim()) {
    return status.message_en.trim();
  }
  switch (status.status) {
    case 'queued':
      return 'Your translation is queued and will start shortly.';
    case 'parsing':
      return 'Parsing the document and reading its structure.';
    case 'translating':
      return 'Translating the manuscript into the target language.';
    case 'rendering':
      return 'Rendering the translated output for review.';
    case 'succeeded':
      return 'The translated document is ready to review and download.';
    case 'failed':
      return 'The run failed. Please review the settings and try again.';
    case 'queue_busy':
      return 'The server queue is full. Please try again in a moment.';
    case 'quota_exceeded':
      return 'Quota was exceeded for this run. Adjust the request and retry.';
    default:
      return 'The current run is updating.';
  }
}

function toRomanPage(pageNumber: number): string {
  const romans = ['I', 'II', 'III', 'IV', 'V'];
  return romans[(pageNumber - 1) % romans.length] ?? 'I';
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [settings, setSettings] = useState<JobSettings>(defaultSettings);
  const [status, setStatus] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [sourceLanguage, setSourceLanguage] = useState<SourceLanguage>('Latin');
  const [specialization, setSpecialization] = useState<Specialization>('academic');
  const [preserveFootnotes, setPreserveFootnotes] = useState(true);
  const [activeNav, setActiveNav] = useState<NavigationItemId>('documents');
  const [activePanel, setActivePanel] = useState<OverlayPanel | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [resolvedPageCount, setResolvedPageCount] = useState<number | null>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const headerRef = useRef<HTMLElement | null>(null);
  const viewerRef = useRef<HTMLElement | null>(null);
  const settingsRef = useRef<HTMLElement | null>(null);
  const statusRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!status?.job_id) {
      return;
    }
    const stop = pollJob(
      status.job_id,
      (next) => {
        startTransition(() => {
          setStatus(next);
        });
      },
      (pollError) => {
        setError(pollError.message);
      },
    );
    return stop;
  }, [status?.job_id]);

  useEffect(() => {
    if (status?.status === 'rendering' || status?.status === 'succeeded') {
      void preloadPdfCanvasPreview();
    }
  }, [status?.status]);

  useEffect(() => {
    if (status?.artifacts?.translated_pdf) {
      setResolvedPageCount(null);
      setPageNumber(1);
    }
  }, [status?.artifacts?.translated_pdf]);

  useEffect(() => {
    if (!activePanel) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (panelRef.current?.contains(target)) {
        return;
      }
      if (target instanceof HTMLElement && target.closest('[data-panel-trigger="true"]')) {
        return;
      }
      setActivePanel(null);
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setActivePanel(null);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [activePanel]);

  const applySpecialization = (value: Specialization) => {
    setSpecialization(value);
    setSettings((current) => ({
      ...current,
      provider: 'ctranslate2',
      renderLayoutEngine: value === 'legal' ? 'pretext' : 'legacy',
      adjustLetterSpacing: value !== 'general',
    }));
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const resetWorkspace = () => {
    setFile(null);
    setSettings(defaultSettings);
    setStatus(null);
    setError('');
    setIsSubmitting(false);
    setZoomPercent(100);
    setPageNumber(1);
    setResolvedPageCount(null);
    setActiveNav('documents');
    setActivePanel(null);
  };

  const startNewTranslation = () => {
    resetWorkspace();
    window.setTimeout(() => {
      openFilePicker();
    }, 0);
  };

  const submit = async () => {
    if (!file) {
      openFilePicker();
      return;
    }
    setIsSubmitting(true);
    setError('');
    try {
      const job = await createJob(file, settings);
      setStatus({ job_id: job.job_id, status: 'queued', stage: 'upload', progress: 0 });
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : 'Failed to create the translation job.',
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePrimaryAction = () => {
    if (status?.status === 'succeeded') {
      startNewTranslation();
      return;
    }
    if (!file) {
      openFilePicker();
      return;
    }
    void submit();
  };

  const handleDownload = () => {
    if (!status?.artifacts?.translated_pdf) {
      return;
    }
    window.open(status.artifacts.translated_pdf, '_blank', 'noopener,noreferrer');
  };

  const handleSwapLanguages = () => {
    const previousSource = sourceLanguage;
    const previousTarget = settings.targetLanguage as SourceLanguage;
    setSourceLanguage(previousTarget);
    setSettings((current) => ({
      ...current,
      targetLanguage: previousSource,
    }));
  };

  const handleZoomIn = () => {
    setZoomPercent((current) => Math.min(MAX_ZOOM, current + ZOOM_STEP));
  };

  const handleZoomOut = () => {
    setZoomPercent((current) => Math.max(MIN_ZOOM, current - ZOOM_STEP));
  };

  const handlePreviousPage = () => {
    setPageNumber((current) => Math.max(1, current - 1));
  };

  const handleNextPage = () => {
    setPageNumber((current) => Math.min(resolvedPageCount ?? TOTAL_PAGES, current + 1));
  };

  const togglePanel = (panel: OverlayPanel) => {
    setActivePanel((current) => (current === panel ? null : panel));
  };

  const handleNavAction = (item: NavigationItemId) => {
    setActiveNav(item);
    switch (item) {
      case 'home':
        headerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setActivePanel('guidelines');
        return;
      case 'documents':
        viewerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        setActivePanel(null);
        return;
      case 'history':
        if (statusRef.current) {
          statusRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
          settingsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        setActivePanel('archives');
        return;
      case 'settings':
        settingsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        setActivePanel(null);
        return;
      default:
        return;
    }
  };

  const selectedFileName = file?.name ?? 'The_Gallic_Wars_Book_I.pdf';
  const viewerSrc =
    status?.status === 'succeeded'
      ? status?.artifacts?.translated_pdf || ''
      : '';
  const statusLabel = mapStatusLabel(status);
  const statusCopy = mapStatusCopy(status, file);
  const canDownload = Boolean(status?.artifacts?.translated_pdf);
  const isJobActive = activeStatuses.has(status?.status ?? '');
  const canRetry = retryableStatuses.has(status?.status ?? '');
  const isPreviewResolving = Boolean(viewerSrc && resolvedPageCount === null);
  const totalPageCount = viewerSrc ? resolvedPageCount ?? 1 : TOTAL_PAGES;
  const pageLabel = isPreviewResolving
    ? 'Loading result…'
    : `Page ${pageNumber} of ${totalPageCount}`;
  const selectedPage = manuscriptPages[(pageNumber - 1) % manuscriptPages.length] ?? manuscriptPages[0];
  const viewerClasses = [
    'viewer-page',
    viewerSrc ? 'has-preview' : '',
    zoomPercent > 100 ? 'zoom-large' : '',
    zoomPercent < 100 ? 'zoom-small' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const artifactEntries = [
    { label: 'Translated PDF', href: status?.artifacts?.translated_pdf },
    { label: 'Detected Boxes', href: status?.artifacts?.detected_boxes_pdf },
    { label: 'Structured JSON', href: status?.artifacts?.structured_json },
    { label: 'Result Markdown', href: status?.artifacts?.result_md },
  ].filter((entry) => Boolean(entry.href));

  const overlayMeta =
    activePanel === 'guidelines'
      ? {
          title: 'Guidelines',
          description: 'Use one PDF, one target language, and one clear translation pass.',
          items: [
            'Upload the source PDF with New Translation.',
            'Check language direction and engine specialization.',
            'Start the run, then review the output in the same frame.',
          ],
        }
      : activePanel === 'library'
        ? {
            title: 'Library',
            description: artifactEntries.length
              ? 'Current run artifacts are ready to open.'
              : 'Artifacts will appear here after a completed translation.',
            links: artifactEntries,
          }
        : activePanel === 'archives'
          ? {
              title: 'Archives',
              description: status?.job_id
                ? 'The current run is available in the workspace.'
                : 'No archived run is available yet.',
              items: status?.job_id
                ? [
                    `Job ID: ${status.job_id}`,
                    `Status: ${statusLabel}`,
                    `Message: ${statusCopy}`,
                  ]
                : ['Run one translation to create the first archive entry.'],
            }
          : activePanel === 'notifications'
            ? {
                title: 'Notifications',
                description: status
                  ? 'Live run status is being tracked here.'
                  : 'There is no active notification right now.',
                items: status ? [`${statusLabel}: ${statusCopy}`] : ['No active run.'],
              }
            : activePanel === 'account'
              ? {
                  title: 'Account',
                  description: 'Current workspace and runtime summary.',
                  items: [
                    `Provider: ${settings.provider}`,
                    `Target: ${settings.targetLanguage}`,
                    `Zoom: ${zoomPercent}%`,
                  ],
                }
              : null;

  return (
    <WorkbenchShell
      activeNav={activeNav}
      onNavAction={handleNavAction}
      onPrimaryAction={startNewTranslation}
      primaryLabel="New Translation"
    >
      <header ref={headerRef} className="editor-topbar">
        <div className="editor-title">
          <span className="material-symbols-outlined" aria-hidden="true">
            auto_stories
          </span>
          <div>
            <h2>{selectedFileName}</h2>
          </div>
        </div>

        <div className="editor-actions">
          <nav className="editor-links" aria-label="Reference links">
              <button
                type="button"
                data-panel-trigger="true"
                className={activePanel === 'guidelines' ? 'is-active' : undefined}
                onClick={() => togglePanel('guidelines')}
              >
                Guidelines
              </button>
              <button
                type="button"
                data-panel-trigger="true"
                className={activePanel === 'library' ? 'is-active' : undefined}
                onClick={() => togglePanel('library')}
              >
                Library
              </button>
              <button
                type="button"
                data-panel-trigger="true"
                className={activePanel === 'archives' ? 'is-active' : undefined}
                onClick={() => togglePanel('archives')}
              >
                Archives
            </button>
          </nav>
          <div className="editor-icons">
            <button
              type="button"
              aria-label="Notifications"
              data-panel-trigger="true"
              onClick={() => togglePanel('notifications')}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                notifications
              </span>
            </button>
            <button
              type="button"
              aria-label="Account"
              data-panel-trigger="true"
              onClick={() => togglePanel('account')}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                account_circle
              </span>
            </button>
          </div>
        </div>
      </header>

      {overlayMeta ? (
        <div ref={panelRef} className="editor-overlay-panel" role="dialog" aria-label={overlayMeta.title}>
          <div className="editor-overlay-head">
            <div>
              <strong>{overlayMeta.title}</strong>
              <p>{overlayMeta.description}</p>
            </div>
            <button
              type="button"
              aria-label="Close panel"
              onClick={() => setActivePanel(null)}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                close
              </span>
            </button>
          </div>
          {overlayMeta.items ? (
            <div className="editor-overlay-list">
              {overlayMeta.items.map((item) => (
                <p key={item}>{item}</p>
              ))}
            </div>
          ) : null}
          {overlayMeta.links ? (
            <div className="editor-overlay-links">
              {overlayMeta.links.map((link) => (
                <a key={link.label} href={link.href} target="_blank" rel="noreferrer">
                  {link.label}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <main className="translation-stage">
        <section ref={viewerRef} className="viewer-shell">
          <div className="viewer-toolbar">
            <div className="viewer-toolbar-group">
              <button
                type="button"
                aria-label="Zoom in"
                onClick={handleZoomIn}
                disabled={zoomPercent >= MAX_ZOOM}
              >
                <span className="material-symbols-outlined" aria-hidden="true">
                  zoom_in
                </span>
              </button>
              <button
                type="button"
                aria-label="Zoom out"
                onClick={handleZoomOut}
                disabled={zoomPercent <= MIN_ZOOM}
              >
                <span className="material-symbols-outlined" aria-hidden="true">
                  zoom_out
                </span>
              </button>
            </div>

            <span className="viewer-page-label">{pageLabel}</span>

            <div className="viewer-toolbar-group">
              <button
                type="button"
                aria-label="Previous page"
                onClick={handlePreviousPage}
                disabled={isPreviewResolving || pageNumber <= 1}
              >
                <span className="material-symbols-outlined" aria-hidden="true">
                  chevron_left
                </span>
              </button>
              <button
                type="button"
                aria-label="Next page"
                onClick={handleNextPage}
                disabled={isPreviewResolving || pageNumber >= totalPageCount}
              >
                <span className="material-symbols-outlined" aria-hidden="true">
                  chevron_right
                </span>
              </button>
            </div>
          </div>

          <div className="viewer-canvas">
            <div className={viewerClasses}>
              {viewerSrc ? (
                <Suspense
                  fallback={
                    <div className="pdf-preview-shell">
                      <div className="pdf-preview-state">Preparing the translated preview…</div>
                    </div>
                  }
                >
                  <PdfCanvasPreview
                    pageNumber={pageNumber}
                    src={viewerSrc}
                    zoomPercent={zoomPercent}
                    onDocumentLoaded={(pageCount) => {
                      setResolvedPageCount(pageCount);
                      setPageNumber((current) => Math.min(current, pageCount));
                    }}
                  />
                </Suspense>
              ) : (
                <article className="manuscript-placeholder">
                  <h3>
                    <span>Commentarii de Bello</span>
                    <span>Gallico</span>
                  </h3>
                  <div className="manuscript-body">
                    {selectedPage.map((paragraph, index) => (
                      <p key={`${pageNumber}-${index}`} className={index === 0 ? 'dropcap' : undefined}>
                        {paragraph}
                      </p>
                    ))}
                  </div>
                </article>
              )}

              {!viewerSrc ? <div className="viewer-page-number">— {toRomanPage(pageNumber)} —</div> : null}
            </div>
          </div>
        </section>

        <aside ref={settingsRef} className="settings-shell">
          <div className="settings-head">
            <h3>Translation Settings</h3>
            <p>Metadata configuration</p>
          </div>

          <div className="settings-body">
            <section className="settings-group">
              <label htmlFor="source-language">Source Language</label>
              <div className="select-wrap">
                <select
                  id="source-language"
                  value={sourceLanguage}
                  onChange={(event) => setSourceLanguage(event.target.value as SourceLanguage)}
                >
                  {sourceLanguageOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <span className="material-symbols-outlined" aria-hidden="true">
                  expand_more
                </span>
              </div>
            </section>

            <div className="swap-row">
              <button type="button" onClick={handleSwapLanguages} aria-label="Swap languages">
                <span className="material-symbols-outlined" aria-hidden="true">
                  swap_vert
                </span>
              </button>
            </div>

            <section className="settings-group">
              <label htmlFor="target-language">Target Language</label>
              <div className="select-wrap">
                <select
                  id="target-language"
                  value={settings.targetLanguage}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      targetLanguage: event.target.value,
                    }))
                  }
                >
                  {targetLanguageOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <span className="material-symbols-outlined" aria-hidden="true">
                  expand_more
                </span>
              </div>
            </section>

            <section className="settings-group">
              <label>Engine Specialization</label>
              <div className="engine-list">
              {specializationOptions.map((option) => {
                  const active = option.value === specialization;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      className={`engine-option${active ? ' active' : ''}`}
                      onClick={() => applySpecialization(option.value)}
                    >
                      <div>
                        <strong>{option.title}</strong>
                        <span>{option.description}</span>
                      </div>
                      <span className="material-symbols-outlined" aria-hidden="true">
                        {active ? 'check_circle' : 'radio_button_unchecked'}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            <div className="toggle-row">
              <span>Preserve Footnotes</span>
              <button
                type="button"
                className={`toggle-switch${preserveFootnotes ? ' on' : ''}`}
                aria-pressed={preserveFootnotes}
                onClick={() => setPreserveFootnotes((current) => !current)}
              >
                <span />
              </button>
            </div>

            {file || status || error ? (
              <div ref={statusRef} className="settings-note">
                <div className="settings-note-head">
                  <strong>Run Status</strong>
                  <span className={`status-pill status-${status?.status ?? 'idle'}`}>{statusLabel}</span>
                </div>
                <p>{error || statusCopy}</p>
              </div>
            ) : null}
          </div>

          <div className="settings-footer">
            <button
              className="primary-action"
              type="button"
              onClick={handlePrimaryAction}
              disabled={isSubmitting || isJobActive}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                {!file ? 'upload_file' : status?.status === 'succeeded' ? 'add' : canRetry ? 'refresh' : 'translate'}
              </span>
              {!file
                ? 'Select PDF'
                : status?.status === 'succeeded'
                  ? 'New Translation'
                  : canRetry
                    ? 'Retry Translation'
                    : 'Start Translation'}
            </button>

            <button
              className="secondary-action"
              type="button"
              onClick={handleDownload}
              disabled={!canDownload}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                download
              </span>
              Download PDF
            </button>
          </div>
        </aside>
      </main>

      <input
        ref={fileInputRef}
        className="hidden-file-input"
        type="file"
        accept="application/pdf"
        onChange={(event) => {
          const nextFile = event.target.files?.[0] ?? null;
          setFile(nextFile);
          setStatus(null);
          setError('');
          setPageNumber(1);
          setResolvedPageCount(null);
        }}
      />
    </WorkbenchShell>
  );
}
