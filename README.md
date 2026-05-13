# BCT Check-in Planner

Intern værktøj til at planlægge biweekly 1:1 check-ins for BCT.

Projektet er nu migreret til en Django-webapp med:
- Google Workspace login (kun domænet `blackcapitaltechnology.com`)
- server-side persistence via Django models/API
- eksisterende planner-UX bevaret via den nuværende `checkin-planner.html`

## Features

- **3 teams × 3 managers, biweekly rotation** — automatisk rotation så hver manager ser hvert team én gang pr. 6-ugers cyklus.
- **Drag-and-drop team-fordeling** med real-time opdatering af kalender + per-medarbejder view.
- **Projekter som tags** — opret projekter, tildel medlemmer, se hvor projekt-folk er fordelt på tværs af check-in teams.
- **Live Google Calendar via OAuth + Calendar API** — managers logger ind én gang, siden henter free/busy direkte og opretter check-in events programmatisk med automatisk invitation til medarbejderen.
- **Visuel slot-grid** — Man-Fre kolonner med alle ledige 15-min slots pr. dag, en uge ad gangen, med ← → pile til at navigere mellem uger.
- **Click-to-book** — klik et slot → modal med titel, varighed, agenda → "Opret i Google Calendar" opretter eventet direkte i din kalender og sender invitation.
- **Auto-sliding kalender** — viser de 4 næste sessioner, slider automatisk frem når en session er forbi.
- **Fallback ICS upload** — træk .ics filer for statisk free/busy snapshot hvis OAuth ikke kan bruges.

## Ny arkitektur (Django)

- Backend: Django (`backend/`) med auth, models og API
- Auth: Google OAuth2 (social-auth-app-django), domæne-restricted
- Frontend: eksisterende planner-side, nu serveret bag login
- Data-flow:
  - `GET /api/state` henter planner-state fra DB
  - `PUT /api/state/update` gemmer planner-state til DB (manager/admin-rolle)
  - Browser bruger stadig local cache, men DB er nu source-of-truth

## Lokal udvikling (Django)

> Ny dev på projektet? Brug den fulde, copy-paste-venlige guide her:
> [`docs/local-setup.md`](docs/local-setup.md).

Kort version:

1. Installer dependencies:
   - `python -m pip install -r requirements.txt`
2. Kopiér `backend/.env.example` til `backend/.env` og udfyld
   `DJANGO_SECRET_KEY`, `GOOGLE_OAUTH2_KEY`, `GOOGLE_OAUTH2_SECRET`.
   Filen indlæses automatisk af `manage.py`/`wsgi.py`/`asgi.py`.
3. Kør migrationer:
   - `python backend/manage.py migrate`
4. Seed baseline data:
   - `python backend/manage.py seed_planner`
5. Opret admin (valgfrit):
   - `python backend/manage.py createsuperuser`
6. Start server:
   - `python backend/manage.py runserver`

Åbn derefter:
- `http://127.0.0.1:8000/accounts/login/` (Google sign-in)
- `http://127.0.0.1:8000/home/` (planner home)
- `http://127.0.0.1:8000/app/` (selve planneren)

## Roller og adgang

- Alle loggede-in brugere kan læse planner-data.
- Kun brugere i gruppen `manager` eller `admin` (eller superuser) kan skrive planner-data via API.
- Grupper kan styres i Django admin (`/admin`).

## Onboarding API

Et separat headless service i samme Django-projekt der lader ERP-systemet
oprette nye medarbejdere og lader HR-værktøjer markere onboarding-steps
færdige via REST. Onboardees logger aldrig ind (de gemmes som
`is_active=False` Django-brugere så de ikke kan tilgå check-in-planneren).

- Endpoints: se [docs/onboarding-api.md](docs/onboarding-api.md).
- Auth: shared API key i `ONBOARDING_API_TOKEN` env var (header
  `X-API-Key: ...`). Tom = endpoints svarer 503.
- Flow templates bygges i Django admin under `/admin/onboarding/`.
- Seed default flow: `python backend/manage.py seed_onboarding`.

## Tests

Kør backend tests:
- `python backend/manage.py test apps.planner.tests apps.accounts.tests apps.onboarding.tests`

## Render deployment (staging + production)

### Filer der bruges til deploy
- `render.yaml` (service + database definition)
- `Procfile` (gunicorn start command)
- `runtime.txt` (python version fallback)

### Miljøvariabler

Fælles:
- `DJANGO_ENVIRONMENT` = `staging` eller `production`
- `DJANGO_DEBUG` = `False`
- `DJANGO_SECRET_KEY` = stærk secret
- `DJANGO_ALLOWED_HOSTS` = dit render-domæne
- `DJANGO_CSRF_TRUSTED_ORIGINS` = `https://<dit-domæne>`
- `DATABASE_URL` = Render Postgres connection string
- `GOOGLE_OAUTH2_KEY` = Google OAuth client id
- `GOOGLE_OAUTH2_SECRET` = Google OAuth client secret
- `GOOGLE_WORKSPACE_DOMAIN` = `blackcapitaltechnology.com`

Sikkerhed (anbefalet):
- `DJANGO_SECURE_SSL_REDIRECT=True`
- `DJANGO_SECURE_HSTS_SECONDS=31536000`
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True`
- `DJANGO_SECURE_HSTS_PRELOAD=True`

### Render setup (første gang)
1. Opret database og web services via `render.yaml` (staging + prod).
2. Sæt env vars for begge services.
3. Tilføj Google OAuth callback URIs:
   - `https://<staging-domain>/auth/complete/google-oauth2/`
   - `https://<prod-domain>/auth/complete/google-oauth2/`
4. Deploy staging først.
5. Verificér staging smoke tests.
6. Deploy production.

### Migration/seed rækkefølge
Build/deploy kører:
1. `pip install -r requirements.txt`
2. `python backend/manage.py collectstatic --noinput`
3. `python backend/manage.py migrate`

Seed køres kun ved første tomme installation:
- `python backend/manage.py seed_planner`

### Smoke-test checklist efter deploy
- `GET /healthz` returnerer HTTP 200.
- Login via Google virker for `@blackcapitaltechnology.com`.
- `GET /api/state` returnerer data for logget ind bruger.
- `GET /api/rotation` returnerer 4 sessioner.
- `POST /api/bookings` opretter en CheckInMeeting + Google event (test
  med en throwaway dato).
- Ændring i planner UI bliver persisted efter refresh.
- Static assets loader korrekt (ingen 404 på `/static/...`).
- CI workflow er grøn på seneste commit/PR.

### Backup & restore drill (kør hvert kvartal)
1. Render Postgres tager dagligt snapshot (default 7-dages retention på
   starter-plan, 30 dage på paid). Verificér i Render dashboard →
   `checkin-planner-db` → **Backups**.
2. Drill: spin en midlertidig instans op fra seneste snapshot.
   - Render dashboard → snapshot → **Restore to new database**.
   - Sæt en `DATABASE_URL` env var på en *staging* web-service der peger
     på den restored DB.
   - Kør `python backend/manage.py check --database default` og verificér
     at `GET /api/state` returnerer forventet data.
3. Slet drill-databasen efter verification så vi ikke betaler for den.
4. Dokumentér restore-tid (RTO) og data-loss-vindue (RPO) i internt
   runbook efter hver drill.

### Server-side Google Calendar (Phase 2)
- Managers logger ind én gang via `/accounts/login/`. social-auth gemmer
  deres `refresh_token` på `UserSocialAuth.extra_data`.
- Backend mintet kortvarige access tokens via
  `apps.planner.google.credentials.credentials_for_user`.
- `/api/freebusy` og `/api/bookings` kalder Google fra serveren — browseren
  holder ikke længere tokens. Hvis tokenet udløber, returnerer endpoints
  `401 {"needs_consent": true}` og frontenden bouncer brugeren gennem
  re-consent.

### Migrere vækk fra Google Sheet journal (Phase 4)
1. Sæt `USE_GOOGLE_SHEET_JOURNAL=True` midlertidigt så frontenden læser
   fra Sheet under cutover.
2. Kør `python backend/manage.py import_journal_sheet --user <admin@...>`
   med `--dry-run` først, derefter for alvor.
3. Verificér: `JournalEntry.objects.count()` matcher Sheet-row-count.
4. Sæt `USE_GOOGLE_SHEET_JOURNAL=False`. Frontenden routes nu journal CRUD
   gennem `/api/journal-entries/...` og file uploads gennem
   `/api/journal-entries/<id>/files`.
5. Behold Sheet'et som read-only backup i 30 dage før den arkiveres.

## Setup pr. manager

1. Åbn siden, vælg dig selv i manager-dropdown
2. Scroll ned til **"Live Google Calendar (OAuth)"**
3. Klik **Sign in with Google** → vælg din `@blackcapitaltechnology.com`-konto → accepter Calendar permissions
4. Klik **Hent free/busy**
5. Bed dine team-medlemmer dele deres Google Calendar med dig (`Calendar settings → Share with specific people → "See only free/busy"`) hvis de ikke allerede har gjort det

Booking: når du klikker et slot og trykker "Opret i Google Calendar", oprettes eventet direkte i din kalender med medarbejderen som inviteret deltager. Google sender invitationen automatisk.

## Google setup (engangs)

Se `GOOGLE_CLOUD_SETUP.md` — den beskriver nu både legacy frontend-token-flow og Django social-auth callback-flow for Render.

## Privacy

- OAuth access tokens lever kun i hukommelsen — aldrig i `localStorage`.
- FreeBusy API returnerer kun busy/free-tider, ingen event-titler eller indhold.
- `state.oauth.busy` cacher kun start/end-tidspunkter, ingen detaljer.
- State i `localStorage` deles ikke mellem brugere.
