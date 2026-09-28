import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const previewSource = readFileSync(
  new URL('../src/components/PdfCanvasPreview.tsx', import.meta.url),
  'utf8',
);

test('PDF preview uses canvas without a scripting manager', () => {
  assert.match(previewSource, /getDocument\s*\(\s*\{/);
  assert.doesNotMatch(previewSource, /new (PDFScriptingManager|AnnotationLayer)/);
  assert.match(previewSource, /page\.render/);
});
