from __future__ import annotations

import json
import sys
from typing import Any


def _emit_error(message: str, *, detail: str | None = None) -> int:
    if detail:
        sys.stderr.write(f"{message} Detail: {detail}\n")
    else:
        sys.stderr.write(f"{message}\n")
    return 1


def _parse_input() -> list[dict[str, Any]]:
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    payload = json.loads(raw)
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("`items` must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def _measure_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - exercised by runtime smoke tests
        raise RuntimeError(
            "Playwright Python package is not available. Install `playwright`."
        ) from exc

    script = """
    (items) => {
      const PT_TO_PX = 96 / 72;
      const PX_TO_PT = 72 / 96;
      const root = document.getElementById('pretext-root');
      if (!root) {
        throw new Error('pretext-root container is missing.');
      }
      root.innerHTML = '';
      const output = [];

      for (const item of items) {
        const block = document.createElement('div');
        block.style.margin = '0';
        block.style.padding = '0';
        block.style.display = 'block';
        block.style.whiteSpace = 'pre-wrap';
        block.style.wordBreak = 'break-word';
        block.style.overflowWrap = 'break-word';
        block.style.fontFamily = item.font_family || 'sans-serif';

        const widthPt = Number(item.width_pt || 0);
        const fontSizePt = Number(item.font_size_pt || 10);
        const lineHeightPt = Number(item.line_height_pt || 0);

        block.style.width = `${Math.max(widthPt, 1) * PT_TO_PX}px`;
        block.style.fontSize = `${Math.max(fontSizePt, 1) * PT_TO_PX}px`;
        if (Number.isFinite(lineHeightPt) && lineHeightPt > 0) {
          block.style.lineHeight = `${lineHeightPt * PT_TO_PX}px`;
        }

        if (typeof item.letter_spacing_em === 'number' && Number.isFinite(item.letter_spacing_em)) {
          block.style.letterSpacing = `${item.letter_spacing_em}em`;
        }

        block.textContent = String(item.text || '');
        root.appendChild(block);

        const rect = block.getBoundingClientRect();
        const computed = window.getComputedStyle(block);
        const lineHeightPx = parseFloat(computed.lineHeight);
        let measuredLineCount = 1;
        if (Number.isFinite(lineHeightPx) && lineHeightPx > 0) {
          measuredLineCount = Math.max(1, Math.round(rect.height / lineHeightPx));
        } else {
          measuredLineCount = Math.max(1, (String(item.text || '').split('\\n').filter((line) => line.trim().length > 0)).length);
        }

        output.push({
          id: String(item.id || ''),
          measured_height_pt: Number((rect.height * PX_TO_PT).toFixed(3)),
          measured_line_count: measuredLineCount,
        });
      }
      return output;
    }
    """

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise RuntimeError(
                "Unable to launch Chromium. Run `python -m playwright install chromium`."
            ) from exc
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 900})
            page.set_content(
                "<html><head><meta charset='utf-8'></head><body style='margin:0;padding:0;'>"
                "<div id='pretext-root' style='padding:0;margin:0;'></div></body></html>"
            )
            return page.evaluate(script, items)
        finally:
            browser.close()


def main() -> int:
    try:
        items = _parse_input()
    except Exception as exc:
        return _emit_error("Invalid helper input JSON.", detail=str(exc))

    try:
        results = _measure_items(items)
    except Exception as exc:
        return _emit_error("Pretext browser measurement failed.", detail=str(exc))

    json.dump({"results": results}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
