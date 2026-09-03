# Rehyn landing-page sign-in modal — design QA

## Comparison target

- Source visual truth: `D:\repos\rehynai\qa-source-auth-modal.jpg` — the existing Rehyn name, email, and trial-code modal captured from the deployed application.
- Implementation: `D:\repos\rehynai\qa-implementation-auth-modal-revised.jpg` — the same form rendered over the latest animated `rehyn.com` landing page.
- Combined comparison: `D:\repos\rehynai\qa-comparison.jpg`.
- Viewport and density: 1280 × 720 CSS pixels, 1280 × 720 captured pixels, device scale factor 1; no density normalization required.
- State: desktop landing page with the sign-in modal open before any patient information is entered.

## Full-view comparison evidence

The revised implementation preserves the current landing page behind a dark modal backdrop and matches the source form’s centered white card, Rehyn brand, title, supporting sentence, three fields, trial-access hint, and full-width green action. It removes the cross-site navigation that previously exposed the older landing page before the form appeared.

## Focused-region comparison evidence

The two full-resolution captures were also inspected individually because all important controls are readable at 1280 × 720. The input heights, label hierarchy, border treatment, card radius, spacing, and button prominence align closely. Text controls for “Close” and “Show/Hide” are an intentional accessibility refinement for older patients and remain visually quiet.

## Findings and comparison history

### Iteration 1 — blocked

- [P2] Modal height obscured the primary action at a 720-pixel-tall viewport.
  - Evidence: `qa-implementation-auth-modal.jpg` showed an internal scrollbar and the Continue button below the visible fold.
  - Fix: reduced the card width and padding, returned inputs and typography to the source modal’s compact dimensions, and tightened vertical spacing.

### Iteration 2 — passed

- Post-fix evidence: `qa-implementation-auth-modal-revised.jpg` shows the entire form and primary action without clipping or internal scrolling.
- No actionable P0, P1, or P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: system sans-serif stack, weights, sizes, line heights, and hierarchy are consistent with the existing landing page and closely match the source form.
- Spacing and layout rhythm: centered card, field spacing, padding, radius, and button placement match the source proportions; all controls fit at the target viewport.
- Colors and visual tokens: existing Rehyn deep green, warm white, muted copy, semantic error red, borders, and backdrop opacity are reused.
- Image quality and asset fidelity: the existing `logo.svg` brand asset is reused at native sharpness; no placeholder or fabricated brand artwork is present.
- Copy and content: the original patient-facing labels and validation wording are preserved without repetition.

## Interaction and accessibility checks

- Sign in opens the modal without leaving the landing-page URL.
- Start free opens the same modal instead of a second repeated flow.
- Empty and invalid-email states show clear inline errors.
- Trial code visibility toggles between Show and Hide.
- Close dismisses the modal, and the native dialog supports keyboard focus and Escape dismissal.
- All three fields and the primary action remain visible in the target viewport.
- Browser diagnostics after the interaction pass contained no console errors.

## Final result

passed
