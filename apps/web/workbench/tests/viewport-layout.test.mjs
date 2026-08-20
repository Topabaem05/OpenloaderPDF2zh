import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const cssUrl = new URL('../src/viewport.css', import.meta.url);

function ruleBlock(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`));
  assert.ok(match, `Missing CSS rule for ${selector}`);
  return match[1];
}

test('locks the application shell to the dynamic viewport', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const rootBlock = ruleBlock(css, 'html,\nbody,\n#root');
  const shellBlock = ruleBlock(css, '.app-shell');
  const mainBlock = ruleBlock(css, '.shell-main');

  assert.match(rootBlock, /height:\s*100%/);
  assert.match(rootBlock, /overflow:\s*hidden/);
  assert.match(shellBlock, /height:\s*100dvh/);
  assert.match(shellBlock, /overflow:\s*hidden/);
  assert.match(mainBlock, /min-height:\s*0/);
  assert.match(mainBlock, /overflow:\s*hidden/);
});

test('contains viewer and settings content instead of creating scroll regions', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const stageBlock = ruleBlock(css, '.translation-stage');
  const viewerBlock = ruleBlock(css, '.viewer-canvas');
  const settingsBlock = ruleBlock(css, '.settings-body');

  assert.match(stageBlock, /min-height:\s*0/);
  assert.match(viewerBlock, /overflow:\s*hidden/);
  assert.match(viewerBlock, /place-items:\s*center/);
  assert.match(settingsBlock, /overflow:\s*hidden/);
});

test('includes a compact mode for short desktop viewports', async () => {
  const css = await readFile(cssUrl, 'utf8');

  assert.match(css, /@media\s*\(max-height:\s*960px\)\s*and\s*\(min-width:\s*769px\)/);
  assert.match(css, /\.engine-option div > span\s*\{[\s\S]*?display:\s*none/);
});

test('switches between viewer and settings without stacking on narrow screens', async () => {
  const css = await readFile(cssUrl, 'utf8');
  const shellSource = await readFile(new URL('../src/components/WorkbenchShell.tsx', import.meta.url), 'utf8');
  const mainSource = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');

  assert.match(mainSource, /import '\.\/viewport\.css';/);
  assert.match(shellSource, /data-active-nav=\{activeNav\}/);
  assert.match(css, /\.app-shell\[data-active-nav="settings"\] \.viewer-shell/);
  assert.match(css, /\.app-shell\[data-active-nav="settings"\] \.settings-shell/);
});
