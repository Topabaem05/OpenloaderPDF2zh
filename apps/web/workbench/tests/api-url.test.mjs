import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildBackendUrl,
  normalizeApiBaseUrl,
  resolveBackendUrl,
} from '../src/lib/api-url.ts';

test('normalizes a configured backend base URL', () => {
  assert.equal(
    normalizeApiBaseUrl(' https://api.example.com/// '),
    'https://api.example.com',
  );
  assert.equal(normalizeApiBaseUrl(undefined), '');
});

test('builds same-origin and cross-origin API URLs', () => {
  assert.equal(buildBackendUrl('/api/jobs', ''), '/api/jobs');
  assert.equal(
    buildBackendUrl('api/jobs', 'https://api.example.com/'),
    'https://api.example.com/api/jobs',
  );
});

test('resolves relative artifact links without rewriting absolute URLs', () => {
  assert.equal(
    resolveBackendUrl('/files/job/translated_mono.pdf', 'https://api.example.com/'),
    'https://api.example.com/files/job/translated_mono.pdf',
  );
  assert.equal(
    resolveBackendUrl('https://cdn.example.com/result.pdf', 'https://api.example.com'),
    'https://cdn.example.com/result.pdf',
  );
  assert.equal(resolveBackendUrl(undefined, 'https://api.example.com'), undefined);
});
