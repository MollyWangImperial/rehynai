# Rehyn public landing page

This repository powers the public website at [rehyn.com](https://rehyn.com/).

The landing page introduces Rehyn's at-home stroke-recovery experience through a concise, accessible overview of its movement check, rehabilitation plan and progress tracking. The hero uses Rehyn's deep-green visual language, rotating benefit statements and a motion pattern that alternates between a gentle drift and a brief orbit.

## App handoff

Public visitors remain on `rehyn.com`. Only explicit sign-in actions open the secure name, email and trial-code form in the Rehyn application at [rehyn.onrender.com](https://rehyn.onrender.com/).

## Local preview

Serve the repository root with any static HTTP server, for example:

```powershell
python -m http.server 4174
```

Then open `http://localhost:4174/`.

## Deployment

GitHub Pages serves the `main` branch. The custom domain is configured by `CNAME` as `rehyn.com`.
