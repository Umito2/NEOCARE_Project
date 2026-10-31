# NEOCARE test report

## Custom theme colors — 31 October 2026

Users can choose any RGB color through the palette button, HEX entry or five
presets, and restore the default palette. Color and light/dark preferences are
independent and saved per browser/app origin. The interface derives readable
shades; status badges keep their semantic colors and printing stays light.

Validation: **151/151 browser tests passed**, including 21 new custom-color
checks. Coverage includes first-render restoration, short/full HEX input,
invalid values, typing without caret disruption, presets/reset, blocked storage,
cross-tab updates, sign-in/out persistence, keyboard focus, Arabic and English at
320/360/390px, and printing. Black, white and six other extreme/saturated colors
meet the tested 4.5:1 text contrast threshold in both modes. Desktop/mobile
previews were inspected with synthetic data.

The update is deployed to Firebase Hosting and PythonAnywhere, which also serves
the existing Android app. All **21 live Chrome checks** and **20 live HTTP/file
checks** passed. Live checks cover color application, persistence after reload,
mode switching and reset on both origins, then authentication and access
restrictions. One existing live-PDF check remains skipped because there was no
reportable reading. No native Android changes were needed; the physical Android
color dialog was not tested, and HEX entry is available as an alternative.

Evidence: `test-results/frontend/custom-colors-full.tap`,
`test-results/frontend/screenshots/custom-*.png`,
`deployment-artifacts/firebase-browser-live.json`, and
`test-results/live-review-verification.json`.

Illustration follow-up: the family artwork now derives clothing, silhouette,
heart badge, halo and decorative colors from the selected palette. The existing
21 custom-color checks passed again. Purple, pink, white, black and yellow
desktop previews were captured, with distinct clothing shades and natural skin
tones. Evidence: `test-results/frontend/illustration-colors.tap` and
`test-results/frontend/screenshots/illustration-*.png`.

Logo follow-up: the NEOCARE icon, wordmark and tagline retain their original
light/dark colors independently of the custom accent. All 21 existing custom-color
checks passed again. Browser inspection across five custom colors in both modes
confirmed unchanged logo colors while the illustration and buttons still adapt.
Evidence: `test-results/frontend/fixed-logo-colors.tap` and
`test-results/frontend/screenshots/fixed-logo-*.png`.

## Full project review and fixes — 30 October 2026

This review supersedes the older results below. Source, regression tests and
Firebase database rules are committed at
[`66a17cf`](https://github.com/Umito2/NEOCARE_Project/commit/66a17cf2279f8f38eb5280deb3f40f4db0933262).
The corrected PythonAnywhere backend and both Firebase Hosting addresses are live.

### Findings and repairs

| Area | Finding | Repair and evidence |
| --- | --- | --- |
| **Critical: Firebase access** | Live test rules allowed unauthenticated reads and writes until 25 November. A read without credentials returned HTTP 200. | Replaced with deny-client rules in `database.rules.json` and applied them to the live database. Anonymous root/child reads now return 401; authorized Admin and website reads return 200. No test writes were made to patient records. |
| Sensor input | JSON `true` could be converted to the numeric reading `1`. | Reject booleans before numeric conversion with HTTP 422; no invalid reading is stored. |
| Latest dashboard data | An older request could overwrite newer readings, profiles or alert status. | Request ordering keeps the latest response and ignores superseded responses/errors. |
| Session privacy | Expired sessions left private dashboard content visible; late PDF/settings/alert operations could affect the next signed-in session. | Clear private state on current-session 401, guard asynchronous work by session, and reset clinic fields on logout. Old-session 401 responses cannot sign out a newer account. |
| Saved-report delivery | A report could be saved without its email job if the second database write failed. | Commit the alert, PDF and delivery job in one transaction; a failed insertion rolls back all three. |
| Email retries | A stale worker failure could change an already-sent job back to retry. | Preserve sent as a terminal state under a SQLite write transaction. This does not promise exactly-once SMTP delivery. |
| API cache protection | Private JSON responses lacked explicit cache prevention. | All `/api/` responses, including errors and PDFs, send `Cache-Control: private, no-store`. Confirmed in local tests and on the live website. |
| Android PDF export | Activity or renderer recreation while the Save picker was open lost the pending PDF. | Preserve the report in private temporary storage with an opaque saved-state token; remove it after completion/cancellation. All 19 Android tests passed; signed version 1.0.1 is linked below. |
| Backup permissions | Backup files relied on the host's process umask. | Create new snapshot directories as 0700 and SQLite/JSON files as 0600 before writing private content. Existing backups are unchanged. This is permission hardening; no exposure of an existing backup was demonstrated. |

The Firebase finding demonstrates that access was permitted; this review does
not establish whether anyone previously accessed or altered data. No patient
records, accounts or clinical thresholds were changed by these checks.

### Verification

| Suite | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| Python 3.14 on Windows | 244 | 8 | 0 |
| Python 3.12 on Linux | 251 | 1 | 0 |
| Chrome browser regression | 130 | 0 | 0 |
| Android unit tests and Android 16 emulator | 19 | 0 | 0 |
| Live HTTP, file hashes, authentication, cache and Firebase restrictions | 20 | 0 | 0 |
| Live Chrome hosted login, refresh, partitioned cookies and logout | 10 | 1 | 0 |

Linux backend and Android CI passed in
[workflow 41102794978](https://github.com/Umito2/NEOCARE_Project/actions/runs/41102794978).
Android lint and release signing verification also passed.
[Android 1.0.1 release](https://github.com/Umito2/NEOCARE_Project/releases/tag/android-v1.0.1)
uses the same application ID and signing key, with version code 2 for updates
over 1.0.0. The PDF lifecycle regression ran on an Android 16 emulator.

Baseline suites passed before the targeted audit (233 Python passes/5 skips and
114 browser passes). Added regression cases reproduced backend and browser
failures before their fixes. An initial final-suite attempt could not read the
sandbox-restricted `a2wsgi` dependency; rerunning with dependency access completed
successfully. The Windows skips cover POSIX permissions/fork and unavailable
symlink privileges; those checks all passed on Linux. Linux skips the Windows
junction test, which passed on Windows. All 252 distinct Python tests therefore
passed on at least one platform. The live PDF check had no existing reportable reading;
synthetic PDF generation/download tests ran without creating patient readings.

Artifacts: `test-results/full-review-python-final.log`,
`test-results/python-results.json`, `test-results/python-linux-results.json`,
`test-results/frontend/bug-audit-final.tap`,
`test-results/frontend/workflow-races-before.tap`,
`test-results/firebase-access-review.json`,
`test-results/live-review-verification.json`,
`deployment-artifacts/firebase-browser-live.json`, and
`deployment-artifacts/android-test-verification.json`.

Remaining limits: real sensor hardware, clinical recommendation accuracy, actual
SMTP delivery and physical Android phones were not validated. SMTP is still
unconfigured. The local Ollama service was not listening on port 11434 during
this review; local inference was not exercised, while fallback behavior passed
the automated tests. Cloud recommendations remain rules-based; no local AI
model was uploaded. PythonAnywhere still requires its regular free-account renewal.
An Android TLS subresource error may unnecessarily show the full-page retry
screen; this was an unverified candidate, not a reproduced defect in this review.
