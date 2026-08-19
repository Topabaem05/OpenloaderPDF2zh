import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const previewSource = readFileSync(
  new URL('../src/components/PdfCanvasPreview.tsx', import.meta.url),
  'utf8',
);

test('PDF preview disables embedded scripting and eval', () => {
  assert.match(previewSource, /getDocument\s*\(\s*\{/);
  assert.match(previewSource, /enableScripting:\s*false/);
  assert.match(previewSource, /isEvalSupported:\s*false/);
});
