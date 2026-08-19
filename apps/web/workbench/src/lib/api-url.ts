const ABSOLUTE_URL_PATTERN = /^[a-z][a-z\d+.-]*:/i;

export function normalizeApiBaseUrl(value: string | undefined): string {
  return (value ?? '').trim().replace(/\/+$/, '');
}

export function buildBackendUrl(path: string, baseUrl: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const normalizedBaseUrl = normalizeApiBaseUrl(baseUrl);
  return normalizedBaseUrl
    ? `${normalizedBaseUrl}${normalizedPath}`
    : normalizedPath;
}

export function resolveBackendUrl(
  value: string | undefined,
  baseUrl: string,
): string | undefined {
  if (!value || ABSOLUTE_URL_PATTERN.test(value) || value.startsWith('//')) {
    return value;
  }
  return buildBackendUrl(value, baseUrl);
}
