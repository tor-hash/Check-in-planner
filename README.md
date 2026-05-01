# BCT Check-in Planner

Intern værktøj til at planlægge biweekly 1:1 check-ins for BCT. Drag-and-drop teams, automatisk rotation mellem managers, projekt-tags, og live Google Calendar integration via Apps Script.

## Features

- **3 teams × 3 managers, biweekly rotation** — automatisk rotation så hver manager ser hvert team én gang pr. 6-ugers cyklus.
- **Drag-and-drop team-fordeling** med real-time opdatering af kalender + per-medarbejder view.
- **Projekter som tags** — opret projekter, tildel medlemmer, se hvor projekt-folk er fordelt på tværs af check-in teams.
- **Live Google Calendar via Apps Script** — hver manager deployer sit eget Apps Script, siden henter live free/busy via FreeBusy API.
- **Visuel slot-grid** — Man-Fre kolonner med alle ledige 15-min slots pr. dag, en uge ad gangen, med ← → pile til at navigere mellem uger.
- **Click-to-book** — klik et slot → modal med titel, varighed, agenda → "Opret i Google Calendar" prefylder event i din kalender.
- **Auto-sliding kalender** — viser de 4 næste sessioner, slider automatisk frem når en session er forbi.
- **Fallback ICS upload** — hvis du ikke vil bruge Apps Script kan du droppe .ics filer for statisk free/busy snapshot.

## Hosting

Hosted via GitHub Pages. State er per-bruger via `localStorage` — hver manager har sin egen view i sin egen browser.

## Setup pr. manager

1. Åbn siden, vælg dig selv i manager-dropdown
2. Deploy dit eget Apps Script (guide indbygget i siden)
3. Indsæt din script URL i feltet med dit navn
4. Klik "Test alle URLs", så "Refresh nu"
5. Bed dine team-medlemmer dele deres Google Calendar med dig (`Calendar settings → Share with specific people → "See only free/busy"`)

## Privacy

- Apps Script URLs er bearer-secrets — del kun med dig selv
- FreeBusy API returnerer kun travl/ledig tider, ingen event-titler eller indhold
- State i `localStorage` deles ikke mellem brugere
