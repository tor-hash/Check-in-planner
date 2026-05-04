# Check-in Planner — Project Memory

> Read this file at the start of every new chat to understand context before making changes.

## What it is
Internt værktøj til BCT for at planlægge biweekly 1:1 check-ins. 3 teams × 3 managers, biweekly rotation så hver manager ser hvert team én gang pr. 6-ugers cyklus. Drag-and-drop fordeling, projekt-tags, click-to-book mod Google Calendar.

## Hosting & stack
- Static site på **GitHub Pages** (no backend).
- Single-file HTML: `checkin-planner.html` (~3500 linjer, vanilla JS).
- `index.html` redirecter til `checkin-planner.html`.
- State per-bruger via `localStorage`.

## Files
- `checkin-planner.html` — hele appen (HTML/CSS/JS i én fil).
- `index.html` — redirect-stub.
- `README.md` — public docs.
- `GOOGLE_CLOUD_SETUP.md` — engangsopsætning af BCT Internal Tools Cloud project.
- `.nojekyll` — undgår Jekyll-processing på GitHub Pages.

## Calendar integration — CURRENT (OAuth + Calendar API)
Implementeret 2026-05-04, Apps Script-flowet fjernet samme dag efter test.

Manager-flow:
1. Åbn siden → vælg dig selv i manager-dropdown
2. Scroll til "Live Google Calendar (OAuth)" → klik **Sign in with Google**
3. Vælg `@blackcapitaltechnology.com`-konto → accepter Calendar permissions
4. Klik **Hent free/busy** → siden batcher alle managers + medarbejder-kalendere i ét `freeBusy`-call
5. Klik et tomt slot → udfyld → **Opret i Google Calendar** → events.insert med medarbejder som attendee + `sendUpdates=all` (Google sender invite)

Token holdes kun i memory (`oauthState.accessToken`), aldrig i localStorage. Auto-refresh hver 10 min hvis brugeren har checkmarket det.

ICS upload beholdes som permanent fallback for offline / edge cases.

## Cloud setup (engangs, allerede gjort 2026-05-04)
**Project:** `BCT Internal Tools` under organisationen `blackcapitaltechnology.com` (delt project for fremtidige interne værktøjer som Onboarding Planner og PA — hver app får sin egen OAuth Client ID under samme projekt).

**Forudsætning der nu er givet:** admin har givet Tor `roles/resourcemanager.projectCreator` på BCT-org'en.

**Consent screen:** Internal mode → ingen verification, ingen test users, ingen advarselsskærm. App-name = "BCT Internal Tools".

**Scopes:** `calendar.freebusy` + `calendar.events` (flere kan tilføjes senere når Onboarding Planner / PA kommer).

**OAuth Client ID for Check-in Planner:** `895573577859-h2sjmrtjhqku4dheh2nsuon4bnnm8p6t.apps.googleusercontent.com` — hardcoded i `OAUTH_CLIENT_ID`-konstanten øverst i OAuth-modulet i `checkin-planner.html`. Public, sikkert at committe. Authorized JS origins: `https://tor-hash.github.io` + `http://localhost:8000`.

**Når et nyt internt værktøj skal tilføjes:** spring til sektion 4 i GOOGLE_CLOUD_SETUP.md — opret nyt OAuth Client ID under samme `BCT Internal Tools` project. Engangsopsætning er færdig.

## OAuth implementation — hvor det bor i koden
- **GIS script-tag** i `<head>`: `<script src="https://accounts.google.com/gsi/client" async defer></script>`.
- **CSS:** `.oauth-config`, `.oauth-actions`, `details.oauth-help` (~line 690).
- **HTML:** `cal-section` "Live Google Calendar (OAuth)" (~line 935).
- **State:** `state.oauth = { clientId, lastFetch, busy, autoRefresh, lastErrors }`. `loadState` har `delete s.liveCal` for at rense legacy state fra gamle browsere.
- **JS-modul:** kommentarblok "LIVE GOOGLE CALENDAR (OAuth + Calendar API)" (~line 2972) — `OAUTH_CLIENT_ID` constant, `oauthState`, `oauthSignIn`, `oauthEnsureToken`, `oauthFreeBusy`, `oauthRefresh`, `oauthCreateEvent`.
- **Booking:** `evCreateInCalendar` (linje ~1900) — async, bruger `oauthCreateEvent` hvis logget ind, ellers fallback til `buildCalendarUrl` URL-prefill (kun til ICS-only brugere).
- **`getBusy(pid)`:** merger ICS managers + ICS employees + `state.oauth.busy[pid]`.

## Repo
- GitHub: `tor-hash/Check-in-planner` (https://github.com/tor-hash/Check-in-planner)
- GitHub Pages URL: `https://tor-hash.github.io/Check-in-planner/`
- Branches: `main` (production), `feature/oauth-calendar` (legacy migration branch — kan slettes når Apps Script-removal er pushet)

## Conventions
- UI-tekster på dansk.
- Vanilla JS, ingen build step, ingen npm.
- CSS variabler øverst i `<style>` for farver.
- LocalStorage keys er prefixet (tjek koden før nye keys tilføjes).
- OAuth Client ID hardcoded i koden (public-safe). Aldrig commit secrets.

## Delt journal — Google Sheet + Drive (implementeret 2026-05-04)

Journal og rapport-data deles på tværs af de 3 managers via en Google Sheet i en delt Drive-folder. Alle 3 managers ser alle entries for alle medarbejdere. Adgang afgrænses via Drive-permissions på den delte topfolder.

**Resource IDs (hardcoded, public-safe — adgang styres via Drive ACL):**
- Sheet ID: `1--rEDjYldyi7F1qRGyZWhj4pi2ADd9tG9BKazjyeZk8` (Sheet "Check-in Journal", tab "Entries")
- Files folder ID: `11Y5HD1GOdWkAkPew6xqc8TZuWK2-KY-O` (sub-folder "Vedhæftede filer")
- Topfolder (Drive-permissions container): `166c0_IXuiGF2D03jrStT4p0CERrLEIFw`

**OAuth scopes (i `OAUTH_SCOPES`):** `calendar.freebusy` + `calendar.events` + `spreadsheets` + `drive.file`. Eksisterende brugere skal re-consent én gang fordi vi har tilføjet to nye scopes.

**GCP API enablement (engangs, gjort 2026-05-04):** Følgende APIs skal være aktiveret i `BCT Internal Tools`-projektet (project number 895573577859) før koden virker:
- Google Calendar API (allerede slået til ved kalender-implementation)
- Google Sheets API → https://console.cloud.google.com/apis/library/sheets.googleapis.com?project=895573577859
- Google Drive API → https://console.cloud.google.com/apis/library/drive.googleapis.com?project=895573577859

Glemmes en API, returnerer kaldet HTTP 403 med "API has not been used in project ... or it is disabled". Aktivering tager ~30 sek effekt. Næste interne tool (Onboarding Planner / PA) under samme projekt arver allerede aktiveringerne.

**Sheet-skema (én række per entry, header i row 1):**
`id | personId | managerId | date | trivsel | faglig | personlig | udfordringer | maal | noter | opfolgning | files | createdAt | updatedAt | deletedAt`
`files` er JSON-array `[{name, type, size, driveId, webViewLink}]`. Sletninger er soft (deletedAt = epoch ms) så row indices forbliver stabile.

**Sync-model:**
- `journalLoadAll()` kaldes automatisk efter OAuth signin (kun første gang per session). Erstatter `state.journal` med sheet-indhold, filtrerer soft-deleted entries fra UI.
- `saveEntry`/`deleteEntry` skriver lokalt først (saveState), pusher derefter til sheet via `journalUpsertEntry` (write-through). `_rowIndex` gemmes på entry-objektet så efterfølgende edits rammer rigtige række.
- Filer: `handleEntryFiles` uploader direkte til Drive via `driveUploadFile` (multipart). Hvis bruger ikke er logget ind, fallback til base64 i localStorage (max 1MB). `fileChipHtml` håndterer begge formater ved render.
- Status-pill `#journal-sync-status` i journal-toolbar viser 🟢/🟡/🔴/⚪. `refreshJournalSyncIndicator` kaldes på alle hooks.

**UI-knapper i journal-toolbar:**
- `⟳ Hent delt journal` — manuel refresh (ellers kun ved signin)
- `⤴ Importér lokal historik` — engangs-migration: snapshot lokal `state.journal`, pre-flight pull, uploader base64-filer til Drive, append'er til sheet med duplikat-check på entry id

**Hvor det bor i koden (`checkin-planner.html`):**
- Constants `JOURNAL_SHEET_ID`, `JOURNAL_FILES_FOLDER_ID`, `JOURNAL_SHEET_TAB`, `JOURNAL_SHEET_HEADER` lige under `OAUTH_CLIENT_ID` (~line 2980).
- HTML: `.sync-bar` i `panel-journal` (~line 870). CSS: `.sync-bar`, `.sync-pill` (~line 340).
- JS-modul: kommentarblok "SHARED JOURNAL — Google Sheet + Drive upload" (~line 3450). Funktioner: `driveUploadFile`, `sheetsApi`, `journalEnsureHeader`, `rowToEntry`/`entryToRow`, `journalLoadAll`, `journalUpsertEntry`, `journalSoftDeleteEntry`, `migrateLocalJournal`.
- `fileChipHtml`-helper (~line 2001) — håndterer både legacy `dataUrl` og nye `webViewLink`-attachments.
- OAuth callback (~line 3070) kalder `journalLoadAll()` efter signin.
- Event listeners for de to nye knapper i den globale init-blok (~line 3870).

**Adgangskontrol:**
Drive-permissions på topfolderen `166c0_IXuiGF2D03jrStT4p0CERrLEIFw` er sandhedslaget. De 3 managers skal være Editor på topfolderen — Sheet og sub-folder arver. Workspace-domænerestriktion + `drive.file`-scope (kun filer skabt af appen) begrænser API-adgang.

**Test-flow før produktion:**
1. Tor logger ind, ser "🟢 Delt journal" pil. Klikker "Importér lokal historik" — eksisterende lokale entries pushes op i sheet.
2. Manager B åbner siden på sin computer, logger ind → ser Tors entries automatisk efter signin-load.
3. B opretter en ny entry → Tor klikker "Hent delt journal" → ser B's entry.
4. Vedhæftet fil oprettet af B kan åbnes i Drive af Tor (åbner i ny fane mod `webViewLink`).
