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
- **`getBusy(pid)`:** returnerer `state.oauth.busy[pid]` (Google Calendar freeBusy-resultater).

## Repo
- GitHub: `tor-hash/Check-in-planner` (https://github.com/tor-hash/Check-in-planner)
- GitHub Pages URL: `https://tor-hash.github.io/Check-in-planner/`
- Branches: `main` (production). Feature-arbejde sker på `feature/oauth-calendar` og merges til main.

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

## Delt master-data — Google Sheet sync (implementeret 2026-05-04)

**Problemet det løser:** Indtil nu lå alt udover journal kun i hver brugers `localStorage`. Da Tor delte sit GitHub Pages-link med Stefan, så Stefan stadig de gamle (forkerte) emails på Lars m.fl. fordi Tors lokale rettelser aldrig forplantede sig til Stefans browser. Kritisk for et delt værktøj.

**Hvad der nu er delt cloud:** medarbejdere (`state.people` — inkl. emails!), managers (`state.mgrs`), team-rotation (`state.teams`), projekter (`state.projects`), funktion-tags (`state.fnTags`), customDates (`state.customDates`), startDate (`state.startDate`).

**Hvad der bevidst er per-bruger (localStorage only):** `viewedMgrFilter`, `weekOffset`, `oauth.accessToken/clientId/autoRefresh`, `workHours`. UI-præferencer skal være individuelle.

**Ikke synced:** ICS-uploads (`state.ics`) — featuren er ubrugt nu hvor OAuth/freeBusy bærer kalenderen, men koden er beholdt som fallback.

**Schema:** Ny tab `MasterData` i samme sheet (`1--rEDjYldyi7F1qRGyZWhj4pi2ADd9tG9BKazjyeZk8`). Header: `key | json | updatedAt | updatedBy`. Én række per nøgle (de 7 nøgler i `MASTER_KEYS`-konstanten). JSON-payloaden er hele state-feltet for den nøgle.

**Sync-model:**
- `masterLoadAll()` kaldes automatisk efter OAuth signin (efter `journalLoadAll`). Erstatter de relevante `state.*` felter med sheet-indhold, gemmer i localStorage som offline cache.
- Alle save-points (person modal, manager dropdown, projekt modal, fnTags modal, drag-drop, startDate change, shuffle, reset, customDates click/clear) kalder `syncPeople()`/`syncTeams()`/`syncProjects()`/`syncFnTags()`/`syncCustomDates()`/`syncStartDate()` efter `saveState()` — write-through pattern (fire-and-forget).
- Pre-write conflict check: `masterUpsertKey()` GET'er sheet's `updatedAt` for nøglen. Hvis sheet's er nyere end vores `keysSyncedAt[key]`, vises confirm-dialog: "Data ændret af X (timestamp). OK → hent først (dine ændringer går tabt). Annullér → overskriv alligevel". Beskytter mod blind overwrite uden at blokke last-write-wins helt.
- `Reset til standard` overskriver delt data for alle (tydeliggjort i confirm-dialogen).

**UI:**
- Sync-bar `<div class="sync-bar">` placeret lige under header (synlig på alle tabs) med `#master-sync-status` pill (⚪/🟡/🟢/🔴) og to knapper: `⟳ Hent delt data` (manuel refresh) og `⤴ Importér lokal master-data` (engangs-migration).
- `migrateLocalMaster()` — første manager der trykker den efter deploy bliver kanonisk kilde. Hvis sheet allerede har data → spørger om brugeren vil overskrive eller ej. Re-læser localStorage for at få den ægte lokale version (i tilfælde af at masterLoadAll allerede har overskrevet state).

**Hvor det bor i koden (`checkin-planner.html`):**
- Constants `MASTER_SHEET_TAB`, `MASTER_SHEET_HEADER`, `MASTER_KEYS` lige under journal-konstanterne (~line 3480).
- Modul: kommentarblok "SHARED MASTER DATA" (~line 4135) — `masterSync`-state, `masterEnsureHeader`, `masterLoadAll`, `applyMasterKey`, `buildMasterPayload`, `masterUpsertKey`, sync-wrappers, `syncAllMaster`, `migrateLocalMaster`.
- Sync-bar HTML lige efter `<header class="top">` (~line 859).
- Event listeners (`btn-master-pull`, `btn-master-migrate`) i init-blokken efter journal-listeners (~line 4720).
- OAuth callback (~line 3585) kalder `masterLoadAll()` efter `journalLoadAll()` ved første signin.
- Write-through hooks: `evSaveOnly`, `evCreateInCalendar`, custom-date input-listeners, `renderMgrDropdowns`-onchange, `saveModal`, `deletePerson`, `saveProject`, `deleteProject`, `saveFnTags`, drag-drop `onEnd`, `startDate`-change, `btn-reset`, `btn-shuffle`.

**Test-flow / deploy:**
1. Push til main, GitHub Pages bygger.
2. Tor (har den rigtige rettede master-data lokalt) åbner siden, logger ind via OAuth → første signin pull'er en TOM `MasterData`-tab og `masterSync.loaded = true`. Tors state forbliver lokalt korrekt.
3. Tor klikker `⤴ Importér lokal master-data` → confirmer overwrite hvis sheet ikke er tom (er tom på første kør) → 7 syncAllMaster-kald skriver alle 7 nøgler til sheet.
4. Stefan åbner siden på sin computer, logger ind → `masterLoadAll()` kører automatisk → hans state overskrives med Tors korrekte data. Lars' email er nu rigtig hos Stefan også.
5. Hver fremtidig ændring (e.g. ny medarbejder, ny manager, projekt-rename) skrives lokalt + push til sheet. Andre managers ser det ved næste `⟳ Hent delt data` eller næste login.

**Conflict edge case:** Hvis Tor og Stefan rediger den samme nøgle samtidig (f.eks. begge tilføjer en person på 1 minut), vil den anden der trykker gem se confirm-dialogen "Data ændret af X". Last-write-wins kan stadig opstå hvis brugeren vælger "overskriv alligevel" — men så har de fået advarslen.

**Auto-polling (tilføjet 2026-05-05):** Statisk hosting har ingen websockets, så vi approximerer real-time push ved at poll'e en single column hver `POLL_INTERVAL_MS` (20 sek). Master tab: GET `MasterData!C2:C` (kun updatedAt-kolonnen ~7 celler), sammenlign max med vores `keysSyncedAt`, kør `masterLoadAll()` hvis sheet er nyere. Journal tab: samme tilgang med `Entries!N2:N`. Polling pauses når `document.hidden`, og kører immediate poll på `visibilitychange` så manager der tabber tilbage ser fresh data inden for 1 sek. `isModalOpen()` blokerer auto-pull mens en bruger er midt i edit. Polling startes i OAuth signin callback (`startSyncPolling()`) og stoppes i `oauthSignOut`. Bandwidth: enkelt-celle reads ~50 bytes × 3 mgrs × 3 polls/min = trivielt, langt under Sheets API quota.

**Backward compat:**
- LocalStorage-format uændret. Eksisterende brugere skal ikke gøre noget for at bruge appen — uden OAuth virker den lokalt som før.
- `MasterData`-tab oprettes automatisk af `masterEnsureHeader()` første gang nogen pusher.

## Brugervenligheds-runde 1 (implementeret 2026-05-04 efter MVP)

**1. Funktion-tags er nu redigerbare** (tidligere hardkodet ENG/BD/MKT/MGMT)
- `state.fnTags = [{ label, displayName, color }, ...]` — seedes med samme 4 default tags i `defaultFnTags()`.
- `loadState` migrerer ældre state ved at seede `fnTags` hvis array mangler / er tomt.
- Ny knap **⚙ Administrér tags** under legenden i sidebar → åbner `#modal-fntags-bg`. Brugeren kan tilføje/redigere/slette og vælge farve.
- Rename detection: ved gem opdateres alle `p.fn = oldDisplayName` → `newDisplayName` så links til personer ikke knækker.
- `fnBadge(p)` slår nu tag op via `findFnTag(p.fn)` og bruger inline `style="background; color"` (semi-transparent bg via `hexToRgba(color, 0.18)`). Ukendte funktioner falder tilbage til `.badge.oth` styling.
- Person-form (`#f-fn`) populeres dynamisk fra `state.fnTags` + permanent "Other"-option via `populateFnSelect()`.
- Legenden er nu auto-genereret i `renderLegend()` ud fra `state.fnTags` (+ statisk OSLO location-tag bibeholdt).

**2. Projekt-tags på person-kort: cirkel → firkantet tag med navn**
- Ny CSS-klasse `.project-tag` (lille farvet pill, 9px font, max-width 90px, ellipsis).
- `projectTagPill(name)` bruger `projectAbbr()` som forkorter logisk: ≤6 chars → as-is, multi-word → initialer (max 5), ellers første 5 chars. Tooltip viser fulde navn.
- Tekstfarve auto-vælges via `pickTextOn(hex)` (luminance check, dark on light, white on dark).
- Projekter har nu `color`-felt (`{ name, description, color }`); ny farvevælger + Auto-knap + live preview i projekt-modalen.
- `projectColor()` returnerer brugervalgt farve hvis sat, ellers `autoProjectColor()` (samme deterministiske palette som før — backward-compat).
- `projectDots(p)` bruger `projectTagPill`. Den gamle `.project-dot` CSS blev fjernet 2026-05-05.
- Sidebar projekt-rækker bruger stadig `.pswatch` (10×10 firkant) som status-indikator i listen.

**3. OBS-felt på journal-entries**
- Nyt felt `obs` på journal entries — fritekst, "Opmærksomhedspunkt til næste check-in".
- Ny textarea `#je-obs` i journal-modalen (efter Opfølgning, før filer), markeret med gul OBS-badge.
- Tydeligt callout `.obs-callout` i `renderJournalCard()` — gul venstre-bjælke, `⚠️` ikon. **OBS-callout afspejler KUN den allerseneste entry**: når en ny entry logges (uden OBS) forsvinder callout'en automatisk; logges en ny med OBS, erstattes den gamle. Meta-linjen viser dato + manager.
- **VIGTIGT — sorterings-bug fix:** "Seneste entry" beregnes via `compareEntriesDesc` (defineret v. line 2200) som sorterer på `date` desc med `createdAt`/`updatedAt` som tiebreaker. Uden tiebreaker'en holdt stabil sort to entries fra samme dag i indsættelsesrækkefølge → den GAMLE entry endte på index 0 → ny OBS viste sig ikke i overviewet. Alle journal-sort-kald (6 steder) bruger nu denne komparator.
- Manuel rydning: × knap (`.obs-clear`) i callout'en kalder `clearObs(personId, entryId)` som tømmer obs på den specifikke entry, gemmer lokalt og syncher til sheet via `journalUpsertEntry` hvis logget ind. Selve check-in entry'en bevares — kun OBS-noten ryddes.
- OBS er tilføjet til alle felt-arrays i: `renderJournalCard` recent-entries (historisk visning — viser per-entry hvad OBS var), `entryCardHtml` (rapporter), `renderJournalTab` per-person fane.

**Sheet-skema-ændring:** Kolonne `obs` tilføjet i kolonne P (index 15).
- `JOURNAL_SHEET_HEADER` er nu 16 kolonner. `journalEnsureHeader` rewriter row 1 hvis eksisterende har <16 kolonner — eksisterende sheets får automatisk den nye header næste gang nogen logger ind.
- Read range `A2:O` → `A2:P`. Header check `A1:O1` → `A1:P1`. Update range `A:O`/`A{n}:O{n}` → `A:P`/`A{n}:P{n}`.
- `rowToEntry` læser `get(15)` → `obs`. `entryToRow` skriver `obs` som 16. element.

**Hvor det bor i koden (`checkin-planner.html`):**
- Default tags: `defaultFnTags()` (~line 1370).
- `findFnTag`, `hexToRgba`, `fnBadge`, `pickTextOn`, `projectAbbr`, `projectTagPill`, `autoProjectColor` (~line 1430-1500).
- Tag-modal HTML: `#modal-fntags-bg` (~line 1083).
- Tag-modal JS: `openFnTagsModal`/`closeFnTagsModal`/`renderFnTagDraftList`/`addFnTagRow`/`saveFnTags` (~line 3090).
- Legend: `renderLegend()` kaldes fra `renderAll()`.
- OBS callout: `obsHtml` blok i `renderJournalCard` (~line 2207).
- OBS i sheet schema: `JOURNAL_SHEET_HEADER`, `rowToEntry`, `entryToRow` (~line 3170, 3760).

**Backward compat / migration:**
- Eksisterende brugere med v4 localStorage får automatisk `fnTags` seedet i `loadState`. Eksisterende projekter får `color` udledt fra `autoProjectColor(name)` (samme farve som før den ændring) ved load.
- Eksisterende sheet (15 kolonner) får automatisk header genskrevet næste gang en manager logger ind. OBS-feltet er bare tomt på gamle entries.

## Code cleanup (2026-05-05)

Efter master-data sync og auto-polling kom på plads, blev følgende fjernet for at reducere støj:

- **ICS upload feature komplet:** UI-section, `.ics-grid`/drop-zone CSS, `parseICS`/`parseICSDate`/`attachICS`/`handleICSFiles`/`setupDropZone`/`renderICSList`-funktioner, `state.ics`-felt, `hasICS()`-helper. OAuth/freeBusy håndterer nu alt kalender-arbejde. ~200 linjer kode fjernet. `loadState()` har `delete s.ics` for at rense legacy state fra eksisterende localStorage.
- **OAuth Client ID localStorage-override:** input-felt `#oauth-client-id`, `state.oauth.clientId`-felt, change-listener, `oauthRenderConfig` input-håndtering, og fallback i `getOauthClientId()`. Vi har hardcoded `OAUTH_CLIENT_ID`-konstanten — overriden var legacy testing-mekanisme. `loadState()` har `delete s.oauth.clientId`.
- **`.project-dot` CSS:** ubrugt siden runde 1 (erstattet af `.project-tag`).
- **Apps Script-kommentarer:** opdateret til ikke længere at referere til den fjernede Apps Script-flow.
- **Bevaret som fail-safes:** URL-prefill-fallback i `evCreateInCalendar` (`buildCalendarUrl`) og `dataUrl`-base64 fallback til journal-files. De koster intet og dækker netværksfejl.
