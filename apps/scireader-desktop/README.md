# SciReader Desktop

Electron + React + TypeScript desktop shell for the local SciReader workflow.

## Implemented phases

- Phase 0: Electron shell starts, connects to the existing `reflow-service`, and renders the local paper library.
- Phase 1: Imports PDFs, reads Zotero storage, writes `reflow-cache/scireader.sqlite`, and displays title, venue, CCF/SCI/JCR, open-source status, parsing status, and manual stars.
- Phase 2: Opens the existing AI Reflow reader in Electron, starts background parsing, polls progress, reads figures/tables, and provides a DeepSeek paper Q&A panel.
- Phase 3: Uses the existing WebDAV account/config API to register/login, push PDFs and AI cache files, and restore cloud PDFs.

## Run

From the repository root:

```powershell
cmd /c run-scireader-desktop.cmd
```

Or from this directory:

```powershell
cmd /c npm install
cmd /c npm run preview
```

The app stores its own library database at:

```text
reflow-cache/scireader.sqlite
```

Secrets remain in the ignored local config:

```text
reflow-cache/config.json
```
