import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = workerUrl;

interface PdfCanvasPreviewProps {
  pageNumber: number;
  src: string;
  zoomPercent: number;
  onDocumentLoaded?: (pageCount: number) => void;
}

export function PdfCanvasPreview({
  pageNumber,
  src,
  zoomPercent,
  onDocumentLoaded,
}: PdfCanvasPreviewProps) {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const onDocumentLoadedRef = useRef(onDocumentLoaded);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [containerWidth, setContainerWidth] = useState(0);

  useEffect(() => {
    onDocumentLoadedRef.current = onDocumentLoaded;
  }, [onDocumentLoaded]);

  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) {
      return;
    }

    const updateWidth = () => {
      setContainerWidth(shell.clientWidth);
    };

    updateWidth();

    const observer = new ResizeObserver(() => {
      updateWidth();
    });

    observer.observe(shell);
    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let documentProxy: PDFDocumentProxy | null = null;

    const render = async () => {
      setIsLoading(true);
      setError('');

      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = 0;
        canvas.height = 0;
        canvas.style.width = '0px';
        canvas.style.height = '0px';
      }

      try {
        const loadingTask = getDocument(src);
        documentProxy = await loadingTask.promise;

        if (cancelled) {
          await documentProxy.destroy();
          return;
        }

        const pageCount = documentProxy.numPages;
        onDocumentLoadedRef.current?.(pageCount);

        const safePageNumber = Math.min(Math.max(pageNumber, 1), pageCount);
        const page = await documentProxy.getPage(safePageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const shellWidth = containerWidth || shellRef.current?.clientWidth || baseViewport.width;
        const targetWidth = Math.max(240, shellWidth - 48);
        const fitScale = targetWidth / baseViewport.width;
        const viewport = page.getViewport({
          scale: fitScale * (zoomPercent / 100),
        });

        const activeCanvas = canvasRef.current;
        if (!activeCanvas) {
          await documentProxy.destroy();
          return;
        }

        const context = activeCanvas.getContext('2d');
        if (!context) {
          throw new Error('Canvas context is not available.');
        }

        const devicePixelRatio = window.devicePixelRatio || 1;
        activeCanvas.width = Math.floor(viewport.width * devicePixelRatio);
        activeCanvas.height = Math.floor(viewport.height * devicePixelRatio);
        activeCanvas.style.width = `${viewport.width}px`;
        activeCanvas.style.height = `${viewport.height}px`;

        context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
        context.clearRect(0, 0, viewport.width, viewport.height);

        const renderTask = page.render({
          canvasContext: context,
          viewport,
        });

        await renderTask.promise;

        if (!cancelled) {
          setIsLoading(false);
        }
      } catch (renderError) {
        if (!cancelled) {
          setError(
            renderError instanceof Error
              ? renderError.message
              : 'Unable to render the PDF preview.',
          );
          setIsLoading(false);
        }
      }
    };

    void render();

    return () => {
      cancelled = true;
      if (documentProxy) {
        void documentProxy.destroy();
      }
    };
  }, [containerWidth, pageNumber, src, zoomPercent]);

  return (
    <div ref={shellRef} className="pdf-preview-shell">
      <canvas ref={canvasRef} className={`pdf-preview-canvas${isLoading ? ' is-loading' : ''}`} />
      {isLoading ? <div className="pdf-preview-state">Rendering the translated preview…</div> : null}
      {error ? <div className="pdf-preview-state is-error">{error}</div> : null}
    </div>
  );
}

export default PdfCanvasPreview;
