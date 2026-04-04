import { createRequire } from "node:module";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => {
      resolve(data);
    });
  });
}

function normalizeRequests(payload) {
  const rawRequests = payload?.requests;
  if (!Array.isArray(rawRequests)) {
    return [];
  }
  return rawRequests
    .filter((request) => request && typeof request === "object")
    .map((request) => ({
      request_id: String(request.request_id || request.id || "").trim(),
      text: String(request.text || ""),
      font_family_css:
        typeof request.font_family_css === "string" &&
        request.font_family_css.trim()
          ? request.font_family_css.trim()
          : "sans-serif",
      font_size_px: Number(request.font_size_px || 0),
      line_height_px: Number(request.line_height_px || 0),
      max_width_px: Number(request.max_width_px || 0),
      letter_spacing_em:
        typeof request.letter_spacing_em === "number"
          ? request.letter_spacing_em
          : null,
    }))
    .filter((request) => request.request_id);
}

function toFontUrl(renderFontPath) {
  if (typeof renderFontPath !== "string" || !renderFontPath.trim()) {
    return "";
  }
  return pathToFileURL(renderFontPath.trim()).href;
}

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch (error) {
    throw new Error(
      "The Playwright package is not installed. Run `npm install` in tools/pretext_layout_helper/."
    );
  }
}

function resolvePretextModuleUrl() {
  try {
    return pathToFileURL(require.resolve("@chenglou/pretext")).href;
  } catch (error) {
    throw new Error(
      "The @chenglou/pretext package is not installed. Run `npm install` in tools/pretext_layout_helper/."
    );
  }
}

async function measureRequests(payload) {
  const { chromium } = await loadPlaywright();
  const pretextModuleUrl = resolvePretextModuleUrl();
  const requests = normalizeRequests(payload);
  const renderFontUrl = toFontUrl(payload?.render_font_path);
  const scratchDir = await mkdtemp(join(tmpdir(), "pretext-layout-"));
  const scratchHtmlPath = join(scratchDir, "index.html");
  await writeFile(
    scratchHtmlPath,
    `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <script type="module">
      import {
        prepareWithSegments,
        layoutWithLines,
      } from ${JSON.stringify(pretextModuleUrl)};
      window.__PRETEXT__ = {
        prepareWithSegments,
        layoutWithLines,
      };
      window.__PRETEXT_READY__ = true;
    </script>
  </head>
  <body></body>
</html>`
  );

  const browser = await chromium.launch({
    headless: true,
    executablePath: chromium.executablePath(),
    args: ["--allow-file-access-from-files"],
  });

  try {
    const page = await browser.newPage({
      viewport: { width: 1600, height: 1200 },
    });
    await page.goto(pathToFileURL(scratchHtmlPath).href);
    await page.waitForFunction(() => window.__PRETEXT_READY__ === true);

    const results = await page.evaluate(
      async ({ requests: browserRequests, renderFontUrl: browserRenderFontUrl }) => {
        const pretext = window.__PRETEXT__;
        if (!pretext) {
          throw new Error("Pretext bridge did not initialize.");
        }
        const { prepareWithSegments, layoutWithLines } = pretext;
        const PX_PER_PT = 96 / 72;
        const loadedFonts = new Set();

        function measureWithDom(
          text,
          fontFamilyCss,
          fontSizePx,
          lineHeightPx,
          maxWidthPx,
          letterSpacingEm
        ) {
          const block = document.createElement("div");
          block.style.position = "absolute";
          block.style.left = "-100000px";
          block.style.top = "0";
          block.style.visibility = "hidden";
          block.style.margin = "0";
          block.style.padding = "0";
          block.style.display = "block";
          block.style.whiteSpace = "pre-wrap";
          block.style.wordBreak = "break-word";
          block.style.overflowWrap = "break-word";
          block.style.fontFamily = fontFamilyCss;
          block.style.fontSize = `${fontSizePx}px`;
          block.style.lineHeight = `${lineHeightPx}px`;
          block.style.width = `${maxWidthPx}px`;
          if (Number.isFinite(letterSpacingEm)) {
            block.style.letterSpacing = `${letterSpacingEm}em`;
          }
          block.textContent = text;
          document.body.appendChild(block);

          const rect = block.getBoundingClientRect();
          const computed = window.getComputedStyle(block);
          const computedLineHeightPx = parseFloat(computed.lineHeight);
          const scrollWidth = block.scrollWidth;
          document.body.removeChild(block);

          let lineCount = 1;
          if (Number.isFinite(computedLineHeightPx) && computedLineHeightPx > 0) {
            lineCount = Math.max(1, Math.round(rect.height / computedLineHeightPx));
          } else {
            lineCount = Math.max(
              1,
              String(text)
                .split("\n")
                .filter((line) => line.trim().length > 0).length
            );
          }

          return {
            heightPx: rect.height,
            lineCount,
            totalWidthPx: Number(Math.min(scrollWidth, maxWidthPx).toFixed(3)),
          };
        }

        async function loadRenderFont() {
          if (!browserRenderFontUrl || loadedFonts.has(browserRenderFontUrl)) {
            return;
          }
          const face = new FontFace("customrenderfont", `url("${browserRenderFontUrl}")`);
          await face.load();
          document.fonts.add(face);
          await document.fonts.ready;
          loadedFonts.add(browserRenderFontUrl);
        }

        await loadRenderFont();

        const output = {};
        for (const request of browserRequests) {
          const requestId = request.request_id;
          const fontSizePx = Math.max(Number(request.font_size_px) || 0, 1);
          const lineHeightPx = Math.max(Number(request.line_height_px) || 0, fontSizePx * 1.2);
          const maxWidthPx = Math.max(Number(request.max_width_px) || 0, 1);
          const text = String(request.text || "");
          const letterSpacingEm =
            typeof request.letter_spacing_em === "number" &&
            Number.isFinite(request.letter_spacing_em)
              ? request.letter_spacing_em
              : null;
          const fontSpec = `${fontSizePx}px ${request.font_family_css}`;
          let heightPx = lineHeightPx;
          let lineCount = 1;
          let totalWidthPx = maxWidthPx;

          if (letterSpacingEm !== null && Math.abs(letterSpacingEm) > 0.0001) {
            const domMeasurement = measureWithDom(
              text,
              request.font_family_css,
              fontSizePx,
              lineHeightPx,
              maxWidthPx,
              letterSpacingEm
            );
            heightPx = domMeasurement.heightPx;
            lineCount = domMeasurement.lineCount;
            totalWidthPx = domMeasurement.totalWidthPx;
          } else {
            const prepared = prepareWithSegments(text, fontSpec, { whiteSpace: "pre-wrap" });
            const layoutResult = layoutWithLines(prepared, maxWidthPx, lineHeightPx);

            if (typeof layoutResult.height === "number") {
              heightPx = layoutResult.height;
            } else if (typeof layoutResult.totalHeight === "number") {
              heightPx = layoutResult.totalHeight;
            } else if (Array.isArray(layoutResult.lines)) {
              heightPx = Math.max(layoutResult.lines.length, 1) * lineHeightPx;
            }

            if (typeof layoutResult.lineCount === "number") {
              lineCount = Math.max(1, Math.round(layoutResult.lineCount));
            } else if (Array.isArray(layoutResult.lines)) {
              lineCount = Math.max(1, layoutResult.lines.length);
            } else if (lineHeightPx > 0) {
              lineCount = Math.max(1, Math.round(heightPx / lineHeightPx));
            }

            if (typeof layoutResult.totalWidth === "number") {
              totalWidthPx = layoutResult.totalWidth;
            } else if (typeof layoutResult.width === "number") {
              totalWidthPx = layoutResult.width;
            }
          }

          output[requestId] = {
            height_px: Number(heightPx.toFixed(3)),
            line_count: lineCount,
            total_width_px: Number(totalWidthPx.toFixed(3)),
            px_per_pt: PX_PER_PT,
          };
        }
        return output;
      },
      {
        requests,
        renderFontUrl,
      }
    );

    return results;
  } finally {
    await browser.close();
    await rm(scratchDir, { recursive: true, force: true });
  }
}

async function main() {
  try {
    const rawInput = await readStdin();
    const payload = rawInput.trim() ? JSON.parse(rawInput) : {};
    const results = await measureRequests(payload);
    process.stdout.write(`${JSON.stringify(results)}\n`);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    process.stderr.write(`${detail}\n`);
    process.exitCode = 1;
  }
}

await main();
