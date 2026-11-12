# Generate while editors remain open

Both report pages and both PDF APIs use the same pipeline:

1. Force-save each editable file, correlating the callback by document key and a
   unique `userdata`. Wait for its bytes to be stored successfully.
2. Freeze every selected source before converting any of them. Conversion reads
   temporary, unguessable snapshot URLs, never the mutable original URL.
3. Release those URLs on success or failure. Preserve file order, duplicate
   selections, cover pages and PDF layout processing.

Editors keep working. Changes after a file's capture belong to the next report.
Unsynced keystrokes and uncommitted spreadsheet cells may not be included.
Multiple files have individual capture times, not one cross-document transaction
at the instant Generate was clicked.

## Persistent state and recovery

`office_sessions.py` persists keys and the latest acknowledged export copy in
SQLite. The default directory is `backend/.office-state`. Compose mounts
`office_session_data` at `/var/lib/me-smart-office` and sets
`ONLYOFFICE_STATE_DIR`. Keep this volume across backend replacements and include
it in backups. The Docker build excludes local state and environment secrets.

Generate force saves store a separate durable copy; they do not overwrite the
live object. The normal final-save callback writes the original to object
storage, then closes the session. Delayed exports cannot overwrite the final
save. New sessions receive a new key even if ETag did not change. Editors joining
an active session retain its key. The editor source endpoint can serve the
durable copy if Document Server reloads before the final save.

On first access, the previous integration's ETag-based key is adopted to allow
existing sessions to finish saving. Unknown/superseded keys are rejected. Failed
storage writes return a nonzero callback error rather than false acknowledgement.

There is no silent fallback after a timeout or save failure. Command error 4
(no changes) uses only a confirmed copy or the original when no unresolved save
exists. Manual/timer force-save callbacks have no ordering token and invalidate
that shortcut until a new correlated save or final save succeeds. If retrying
Generate still fails to confirm saving, save/close that document and resolve the
ONLYOFFICE/storage error before retrying.

The existing ZIP API downloads current original objects. It is not an archive
of the PDF snapshot and can differ when editing continues after Generate.

## Deploy and verify

This retains the existing **one Uvicorn process / one backend instance** limit.
SQLite persistence does not make the callback waiters, snapshot URLs or PDF jobs
multi-instance. Multiple workers require shared coordination and storage.

From `backend`, deploy backend and HTML together:

```powershell
podman compose up -d --build backend
```

No document migration or database reset is needed. Do not use `compose down -v`.
Keep ONLYOFFICE running during backend-only deployment. Restarting the backend
interrupts temporary report jobs; retry those jobs afterward.

With `requirements.txt` installed, run:

```powershell
python -m unittest discover -s . -p "test_*.py" -v
```

The tests simulate command responses, callbacks, storage failures, simultaneous
exports, restarts, JWT verification and conversion downloads. They do not replace
an end-to-end check against the deployed Document Server. Use a disposable file:

1. Open in two browsers, enter different values and commit the cells.
2. Generate from a third browser while both editors continue editing.
3. Confirm editors stay connected and PDF contains captured values; generate
   again and confirm later committed values appear.
4. Join from another browser after Generate; verify it joins the same session.
5. Close all editors and reopen; verify the final values and a new session key.
6. Confirm save errors fail the report instead of returning stale data.
7. Check Rotating and Static reports, PDF inputs, covers, order and print layout.

References: [force save](https://api.onlyoffice.com/docs/docs-api/additional-api/command-service/forcesave),
[callbacks](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler),
[co-editing keys](https://api.onlyoffice.com/docs/docs-api/get-started/how-it-works/co-editing).
