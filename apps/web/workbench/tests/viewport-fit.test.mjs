import assert from 'node:assert/strict';
import test from 'node:test';

import { calculateContainedPdfScale } from '../src/lib/viewport-fit.ts';

test('contains a PDF page inside both viewport dimensions', () => {
  const scale = calculateContainedPdfScale({
    pageWidth: 600,
    pageHeight: 900,
    containerWidth: 1000,
    containerHeight: 700,
    zoomPercent: 100,
  });

  assert.ok(scale > 0);
  assert.ok(600 * scale <= 1000);
  assert.ok(900 * scale <= 700);
});

test('uses zoom to reduce the inset without creating overflow', () => {
  const zoomedOut = calculateContainedPdfScale({
    pageWidth: 600,
    pageHeight: 900,
    containerWidth: 1000,
    containerHeight: 700,
    zoomPercent: 85,
  });
  const zoomedIn = calculateContainedPdfScale({
    pageWidth: 600,
    pageHeight: 900,
    containerWidth: 1000,
    containerHeight: 700,
    zoomPercent: 135,
  });

  assert.ok(zoomedIn > zoomedOut);
  assert.ok(600 * zoomedIn <= 1000);
  assert.ok(900 * zoomedIn <= 700);
});

test('returns a stable fallback for unavailable geometry', () => {
  assert.equal(
    calculateContainedPdfScale({
      pageWidth: 0,
      pageHeight: 0,
      containerWidth: 0,
      containerHeight: 0,
      zoomPercent: 100,
    }),
    1,
  );
});
