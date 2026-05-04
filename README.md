# BCT Check-in Planner

Intern værktøj til at planlægge biweekly 1:1 check-ins for BCT. Drag-and-drop teams, automatisk rotation mellem managers, projekt-tags, og live Google Calendar integration via Apps Script.

## Features

- **3 teams × 3 managers, biweekly rotation** — automatisk rotation så hver manager ser hvert team én gang pr. 6-ugers cyklus.
- **Drag-and-drop team-fordeling** med real-time opdatering af kalender + per-medarbejder view.
- **Projekter som tags** — opret projekter, tildel medlemmer, se hvor projekt-folk er fordelt på tværs af check-in teams.
- **Live Google Calendar via OAuth + Calendar API** — managers logger ind med Google én gang, siden henter free/busy direkte og kan oprette check-in events programmatisk (med automatisk invitation til medarbejderen). Apps Script-flow findes stadig som legacy under migrationen.
- **Visuel slot-grid** — Man-Fre kolonner med alle ledige 15-min slots pr. dag, en uge ad gangen, med ← → pile til at navigere mellem uger.
- **Click-to-book** — klik et slot → modal med titel, varighed, agenda → "Opret i Google Calendar" prefylder event i din kalender.
- **Auto-sliding kalender** — viser de 4 næste sessioner, slider automatisk frem når en session er forbi.
- **Fallback ICS upload** — hvis du ikke vil bruge Apps Script kan du droppe .ics filer for statisk free/busy snapshot.

## Hosting

Hosted via GitHub Pages. State er per-bruger via `localStorage` — hver manager har sin egen view i sin egen browser.

## Setup pr. manager (NY OAuth-flow)

1. Åbn siden, vælg dig selv i manager-dropdown
2. (Engangs admin-opsætning af Tor: se `GOOGLE_CLOUD_SETUP.md` — resultatet er et OAuth Client ID)
3. Indsæt OAuth Client ID i sektionen "Live Google Calendar (OAuth)"
4. Klik **Sign in with Google** → autorisér Calendar-scopes
5. Klik **Hent free/busy**
6. Bed dine team-medlemmer dele deres Google Calendar med dig (`Calendar settings → Share with specific people → "See only free/busy"`)

Booking: når du klikker et slot og trykker "Opret i Google Calendar", oprettes eventet direkte i din kalender med medarbejderen som inviteret deltager (Google sender invitationen automatisk).

### Legacy: Apps Script-flow
Apps Script-sektionen findes stadig under migrationen, men anbefales ikke til nye managers. Den fjernes når OAuth er testet i produktion.

## Privacy

- Apps Script URLs er bearer-secrets — del kun med dig selv
- FreeBusy API returnerer kun travl/ledig tider, ingen event-titler eller indhold
- State i `localStorage` deles ikke mellem brugere
