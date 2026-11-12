# Static Equipment

Independent frontend pages for `service=Static Equipment`, copied from the current
root pages so their markup, styles, and inline functions can evolve separately.

- Entry: `Package Selection.html`; the shared Service page opens it for Static Equipment.
- Existing root `Package Selection.html` bookmarks with this service redirect here.
- Existing root `Package Default.html` bookmarks with this service redirect here.
- Package pages: `Package Default.html`, `Data.html`, `Progress.html`,
  `QAQC Step.html`, and `Report_Demo.html`.
- Supporting pages: the five report forms, `Editor.html`, and `PDF Stamp.html`.
- `Progress.html` is a placeholder because the original root has no Progress page.
- Home, plant/service selection, login, logo, and the access helper remain
  shared in the parent folder. APIs and storage conventions are unchanged.

Edit files in this folder for Static Equipment changes. Keep links between these
pages relative to this folder; links to shared pages/assets use `../`.
Preserve company, plant, service, and package parameters when navigating.
General Form templates still use the shared backend/storage; copying these pages
does not create a separate set of templates or backend business logic.

The Dockerfile copies this directory into `/app/static-equipment`, served at
`/ui/static-equipment/`. Rebuild the backend image when deploying these changes.
