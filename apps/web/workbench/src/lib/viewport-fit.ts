export interface ContainedPdfScaleInput {
  pageWidth: number;
  pageHeight: number;
  containerWidth: number;
  containerHeight: number;
  zoomPercent: number;
  minZoomPercent?: number;
  maxZoomPercent?: number;
  minInset?: number;
  maxInset?: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

export function calculateContainedPdfScale({
  pageWidth,
  pageHeight,
  containerWidth,
  containerHeight,
  zoomPercent,
  minZoomPercent = 85,
  maxZoomPercent = 135,
  minInset = 12,
  maxInset = 64,
}: ContainedPdfScaleInput): number {
  if (
    pageWidth <= 0 ||
    pageHeight <= 0 ||
    containerWidth <= 0 ||
    containerHeight <= 0
  ) {
    return 1;
  }

  const zoomRange = Math.max(1, maxZoomPercent - minZoomPercent);
  const zoomProgress = clamp((zoomPercent - minZoomPercent) / zoomRange, 0, 1);
  const inset = maxInset - (maxInset - minInset) * zoomProgress;
  const usableWidth = Math.max(1, containerWidth - inset * 2);
  const usableHeight = Math.max(1, containerHeight - inset * 2);

  return Math.min(usableWidth / pageWidth, usableHeight / pageHeight);
}
