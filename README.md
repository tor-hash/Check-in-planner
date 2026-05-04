# BCT Check-in Planner

Intern værktøj til at planlægge biweekly 1:1 check-ins for BCT. Drag-and-drop teams, automatisk rotation mellem managers, projekt-tags, og live Google Calendar integration via OAuth + Calendar API.

## Features

- **3 teams × 3 managers, biweekly rotation** — automatisk rotation så hver manager ser hvert team én gang pr. 6-ugers cyklus.
- **Drag-and-drop team-fordeling** med real-time opdatering af kalender + per-medarbejder view.
- **Projekter som tags** — opret projekter, tildel medlemmer, se hvor projekt-folk er fordelt på tværs af check-in teams.
- **Live Google Calendar via OAuth + Calendar API** — managers logger ind én gang, siden henter free/busy direkte og opretter check-in events programmatisk med automatisk invitation til medarbejderen.
- **Visuel slot-grid** — Man-Fre kolonner med alle ledige 15-min slots pr. dag, en uge ad gangen, med ← → pile til at navigere mellem uger.
- **Click-to-book** — klik et slot → modal med titel, varighed, agenda → "Opret i Google Calendar" opretter eventet direkte i din kalender og sender invitation.
- **Auto-sliding kalender** — viser de 4 næste sessioner, slider automatisk frem når en session er forbi.
- **Fallback ICS upload** — træk .ics filer for statisk free/busy snapshot hvis OAuth ikke kan bruges.

## Hosting

Hosted via GitHub Pages. State er per-bruger via `localStorage` — hver manager har sin egen view i sin egen browser.

## Setup pr. manager

1. Åbn siden, vælg dig selv i manager-dropdown
2. Scroll ned til **"Live Google Calendar (OAuth)"**
3. Klik **Sign in with Google** → vælg din `@blackcapitaltechnology.com`-konto → accepter Calendar permissions
4. Klik **Hent free/busy**
5. Bed dine team-medlemmer dele deres Google Calendar med dig (`Calendar settings → Share with specific people → "See only free/busy"`) hvis de ikke allerede har gjort det

Booking: når du klikker et slot og trykker "Opret i Google Calendar", oprettes eventet direkte i din kalender med medarbejderen som inviteret deltager. Google sender invitationen automatisk.

## Admin setup (engangs)

Se `GOOGLE_CLOUD_SETUP.md` — Tor opsætter ét fælles `BCT Internal Tools` Google Cloud project, opretter OAuth Client ID, og indsætter ID'et i `OAUTH_CLIENT_ID`-konstanten i `checkin-planner.html`.

## Privacy

- OAuth access tokens lever kun i hukommelsen — aldrig i `localStorage`.
- FreeBusy API returnerer kun busy/free-tider, ingen event-titler eller indhold.
- `state.oauth.busy` cacher kun start/end-tidspunkter, ingen detaljer.
- State i `localStorage` deles ikke mellem brugere.
