# Check-in Planner — Project Memory

> Read this file at the start of every new chat to understand context before making changes.

## What it is
Internt værktøj til BCT for at planlægge biweekly 1:1 check-ins. 3 teams × 3 managers, biweekly rotation så hver manager ser hvert team én gang pr. 6-ugers cyklus. Drag-and-drop fordeling, projekt-tags, click-to-book mod Google Calendar.

## Hosting & stack
- Static site på **GitHub Pages** (no backend).
- Single-file HTML: `checkin-planner.html` (~3000 linjer, vanilla JS).
- `index.html` redirecter til `checkin-planner.html`.
- State per-bruger via `localStorage`.

## Files
- `checkin-planner.html` — hele appen (HTML/CSS/JS i én fil).
- `index.html` — redirect-stub.
- `README.md` — public docs.
- `.nojekyll` — undgår Jekyll-processing på GitHub Pages.

## Calendar integration — CURRENT (Apps Script per manager)
Hver manager:
1. Deployer sit eget Apps Script Web App (`doGet` med `Calendar.Freebusy.query`).
2. Indsætter Web App URL i appen (felt pr. manager-navn).
3. App kalder alle konfigurerede script URLs via JSONP for at hente free/busy.

Booking sker via URL prefill (`google.com/calendar/render?...`) — ingen API-skrivning.

ICS upload findes som statisk fallback.

**Smerte ved nuværende model:** hver manager skal igennem Apps Script setup, autorisere scopes, deploye, og holde URL'en hemmelig. Skalerer dårligt og er en barriere for ibrugtagning.

## Calendar integration — PLANNED (Calendar API + OAuth)
Migration besluttet 2026-05-04: erstatte Apps Script med Google Identity Services (GIS) + Calendar API direkte fra browseren.

Manager-flow bliver: "Log ind med Google" → app henter free/busy + (valgfrit) opretter events via `https://www.googleapis.com/calendar/v3/...`. Ingen Apps Script.

**Krav (engangsopsætning af Tor):** se `GOOGLE_CLOUD_SETUP.md`.
- Google Cloud project under Tor's **personlige** konto (Tor er ikke Workspace-admin på BCT, så Internal-pathen er ikke tilgængelig).
- Calendar API enabled.
- OAuth consent screen = **External / Testing**. Loft på 100 test users — hver manager skal tilføjes manuelt.
- Web OAuth Client ID, authorized JS origin = GitHub Pages URL (+ evt. localhost).
- Client ID **hardcoded** som konstant `OAUTH_CLIENT_ID` øverst i scriptet (linje ~3220 i checkin-planner.html). Public, sikkert at committe. Input-feltet i UI'en er fallback for advanced override og auto-skjules når konstanten er sat.

**Beslutninger truffet 2026-05-04:**
- Cloud project = personligt (Tor ikke admin), External Testing-mode. Migration til Internal er muligt senere hvis admin aktiverer "Google Cloud Platform → ON for everyone" i Workspace Admin Console.
- Engangs gul advarselsskærm pr. manager ved første login ("Google hasn't verified this app") — accepteret omkostning. Forklaret i `<details>` i OAuth-sektionen og i GOOGLE_CLOUD_SETUP.md.
- Scopes: `calendar.freebusy` + `calendar.events`.
- Booking opretter event direkte via API (`events.insert` med `sendUpdates=all` → automatisk invite til medarbejderen).
- Apps Script-section beholdes side-by-side under migration; ICS-upload beholdes permanent som fallback.
- Rollout: feature branch `feature/oauth-calendar`, side-by-side først, fjernelse af Apps Script i en senere PR når OAuth er testet.

**Test users — daglig opgave for Tor:**
Når en ny manager skal have adgang: Cloud Console → APIs & Services → OAuth consent screen → Test users → + Add users → indtast email → Save.

**Stadig krævet (samme som i dag):** medarbejdere deler deres kalender free/busy med deres manager i Google Calendar settings.

## OAuth implementation — hvor det bor i koden
- HTML: ny `cal-section` "Live Google Calendar (OAuth)" lige over Apps Script-sektionen (~line 933).
- CSS: `.oauth-config`, `.oauth-actions` (~line 698).
- State: `state.oauth = { clientId, lastFetch, busy, autoRefresh, lastErrors }` (`defaultState`/`loadState`).
- JS-modul: kommentarblok "LIVE GOOGLE CALENDAR (OAuth + Calendar API)" (~line 3217) — `oauthState`, `oauthSignIn`, `oauthEnsureToken`, `oauthFreeBusy`, `oauthRefresh`, `oauthCreateEvent`.
- GIS script-tag: `<script src="https://accounts.google.com/gsi/client" async defer></script>` i `<head>`.
- Booking: `evCreateInCalendar` er nu async — bruger `oauthCreateEvent` hvis logget ind, ellers fallback til `buildCalendarUrl` URL-prefill.
- `getBusy()` foretrækker OAuth-data over Apps Script-data for samme person (ingen double-counting).
- Token holdes kun i memory (`oauthState.accessToken`), aldrig i localStorage.

## Conventions
- UI-tekster på dansk.
- Vanilla JS, ingen build step, ingen npm.
- CSS variabler øverst i `<style>` for farver.
- LocalStorage keys er prefixet (tjek koden før nye keys tilføjes).
