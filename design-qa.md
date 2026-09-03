# Design QA

## Target

The selected Rehyn landing direction: a white branded header, deep-green animated network hero, rotating benefit statement, concise transition message and three product-preview cards.

## Checks completed

- Desktop layout checked at the in-app browser's default 1280 × 720 viewport.
- Responsive layout checked inside a true 390 px-wide browser frame; no horizontal overflow was present.
- Header, hero, statement band and all three preview cards were visually inspected.
- `Start free` and `For families` dialogs were opened and closed successfully.
- `How it works` moves to the product-preview section.
- Only the two explicit sign-in links point to `https://rehyn.onrender.com/`; the page itself has no automatic redirect.
- Rotating copy changes approximately every 2.6 seconds.
- Background motion contains both gentle and rapid phases, with a reduced-motion fallback.
- Runtime console checked with no errors.

final result: passed
