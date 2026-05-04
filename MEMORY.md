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
