# ccfreader

Local Zotero AI Reflow build for Windows.

## What is here

- `reflow-service/`: local Docling + DeepSeek service for PDF extraction, cached translation, paper summaries, figures, and tables.
- `patches/zotero-ai-reflow.patch`: Zotero source changes that replace the native PDF reader entry point with the local AI Reflow reader and add background progress tracking.
- `build-zotero-dev.cmd`: Windows helper for building the patched Zotero source in this workspace.
- `run-zotero-dev.cmd`: starts the local reflow service if needed, then launches the built Zotero app with a local dev profile.
- `apps/scireader-desktop/`: new Electron + React + TypeScript SciReader desktop shell. It reads Zotero storage into `reflow-cache/scireader.sqlite`, talks to the same local reflow service, and provides the cleaner research workspace UI.
- `run-scireader-desktop.cmd`: launches the Electron SciReader desktop app.

## Secrets

Copy `reflow-service/.env.example` to `reflow-service/.env` and set `DEEPSEEK_API_KEY`.
The `.env` file, service logs, caches, virtual environments, generated builds, probe outputs, and test PDFs are ignored by Git.

## Applying the Zotero patch

From a clean Zotero source checkout:

```powershell
git apply ..\patches\zotero-ai-reflow.patch
```

In this workspace the patched checkout lives at `zotero-upstream/`.
