# Remote validation

Validated on 2026-07-27 using a 602-frame patient walking video:

- MediaPipe pose detected in 601/602 frames.
- Video-informed Moco solve: `Solve_Succeeded`.
- Matched-template Moco solve: `Solve_Succeeded`.
- The Chinese report was generated with movement phenotypes, possible functional issues, clinical verification items, activation plots, force plots, and interpretation boundaries.
- No patient video, landmark CSV, generated report, or local patient path is committed.

The validation data remains local and is excluded by `.gitignore`.
