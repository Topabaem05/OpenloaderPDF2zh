# Design System: OpenPDF2ZH Alexandria
**Project ID:** openpdf2zh_gradio

## 1. North Star
The UI follows the Stitch `alexandria/_2` screen directly. It is not a generic dashboard. It is a calm document workspace with a fixed left sidebar, a thin top header, one centered manuscript canvas, and one narrow settings panel.

## 2. Layout Rules
- Use a 3-part desktop frame: left sidebar, main document stage, right settings card.
- Sidebar width stays compact and fixed. It contains brand, four nav items, and one bottom CTA.
- Header stays shallow and spans only the main content area.
- The document stage must feel like one quiet reading surface, not a grid of cards.
- The right card stays narrow and vertically stacked: language inputs, specialization list, footnote toggle, status note, footer actions.
- Keep spacing on an 8pt rhythm wherever possible: 8, 16, 24, 32, 48.
- Use responsive breakpoints at 1280, 1160, 768, and 640. The document and settings columns should stack once the document stage can no longer retain a comfortable reading width.
- On small screens, reduce chrome aggressively before touching document readability. Brand, nav, and utility areas should compress so the manuscript appears as early as possible.
- On mobile, the top header should collapse into a very shallow two-row band. Keep file title and utility actions readable, but do not let the header re-expand into a desktop-like block.

## 3. Visual Language
- Background: warm paper ivory, not pure gray and not bright white.
- Surfaces: tonal layering first, shadows second.
- Corners: softly rounded everywhere, never sharp.
- Borders: use only when they help selection state. Do not outline every container.
- Blue is reserved for active navigation, links, selected specialization, and primary buttons.
- Gold is reserved for toggles and in-progress status.

## 4. Typography
- Use Pretendard as the single typeface across the entire product.
- Sidebar brand can be italicized, but it still uses Pretendard.
- Header and panel titles use strong weight and tight tracking.
- Metadata labels are small, uppercase, and muted.
- Document placeholder text should feel editorial through spacing and alignment, not through a separate font family.
- Keep the header visually shallow. Utility links and metadata should read quieter than the document title and active settings.
- Keep the top-right utility cluster tight. Links and icons should read as one light utility band, not a second navigation bar.
- Top-right utility links must still read as interactive controls. Use quiet pill buttons or equivalent affordance rather than bare text when the hit area would otherwise become ambiguous.
- Keep the top-left file title cluster equally tight. The file icon and title should feel like one label, not a spaced header composition.

## 5. Component Rules
- Sidebar nav: low-contrast default, blue active state with a right-edge emphasis.
- Sidebar nav on desktop should feel crisp rather than pillowy. Keep item spacing and padding restrained.
- Keep the brand and nav visually coupled. The sidebar should read as one quiet column, not separate stacked modules.
- The sidebar CTA should remain clearly primary, but its density should still match the rest of the sidebar. Avoid oversized height or exaggerated tracking.
- Primary button: blue horizontal gradient, strong affordance, contextual label that matches the actual action.
- Secondary button: pale surface fill with blue text, clearly lower emphasis.
- Selects: filled soft-surface fields with no visible browser chrome.
- Specialization cards: stacked list, one selected card only, selected state uses blue stroke and pale blue fill.
- Status note: use a clear heading plus a concise state pill and message. It should support empty, running, success, and retryable states without changing the surrounding frame.
- On mobile, compress the status note before compressing the footer CTA. The state card should stay readable, but it should not push the primary action out of the first follow-up viewport.
- Toolbar and icon buttons must meet a comfortable desktop hit target and visually read as clickable controls, not decorative icons.
- On mobile, all header links, utility icons, nav buttons, and document-toolbar controls must keep a `44px` minimum touch target.
- Do not let mobile section headings grow larger than desktop. Settings titles should tighten, not expand, when the layout compresses.
- Settings density should stay restrained: tighter section gaps, smaller metadata labels, and no oversized explanatory copy.
- On desktop, trim empty vertical space between settings sections before shrinking control readability.
- The document toolbar should read as a thin measurement strip, not a second content block. Keep button clusters compact around the page label.
- Use an 8pt spacing rhythm more strictly inside chrome and settings surfaces. Avoid one-off values like `10px`, `18px`, or `28px` unless they are required to preserve a specific reference proportion.
- On mobile, compress the settings card before sacrificing the document stage. Reduce head/body/footer padding and card height, but keep labels and controls legible.
- On mobile, only the active specialization card should carry supporting copy. Inactive specialization cards should collapse to short, title-only rows.
- On mobile, the disabled secondary action should recede clearly behind the primary CTA. Keep it legible, but visually quiet.

## 6. Document Canvas Rules
- Toolbar is compact and quiet.
- The default canvas should look like an already-open manuscript page.
- Keep the manuscript page physically narrow inside a larger soft reading field.
- Do not place loud upload cards or onboarding tiles inside the document stage.
- File selection should be triggered by the global CTA actions, not by a central hero panel.
- Completed preview must never render as a page-inside-a-page. The rendered PDF page is the page surface.
- Keep the document stage slightly airier than the page itself. The outer canvas padding and toolbar should feel lighter than the right settings card, not heavier.
- On mobile, shrink outer canvas padding before shrinking body text. The first manuscript page should appear as high as possible without feeling cramped.
- On mobile, reduce topbar padding, stage top padding, and settings-head/footer padding before touching manuscript text size. The first page should visibly move upward as chrome compresses.
- The opening paragraph matters disproportionately. Tune drop-cap scale, margin, and first-paragraph line height before changing the rest of the page.

## 7. Behavior Constraints
- Keep backend integration intact through `/api/jobs` and `/api/jobs/{job_id}`.
- The UI may change visual density, but must preserve upload, run, polling, and download behavior.
- Empty, running, success, and error states must keep the same frame so the screen does not reflow dramatically.
