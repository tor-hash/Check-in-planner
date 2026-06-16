# Google Cloud Console — opsætning for BCT Internal Tools

Vi bruger ét fælles Google Cloud project, **BCT Internal Tools**, til alle interne værktøjer (Check-in Planner, Onboarding Planner, PA, fremtidige). Hver app får sin egen OAuth Client ID under det samme projekt.

```
Project: BCT Internal Tools (Internal-app, Workspace-only)
├── Enabled APIs: Calendar (+ Gmail når PA kommer)
├── OAuth consent screen: app-navn "BCT Internal Tools", scopes for alle apps
├── OAuth Client ID #1 → Check-in Planner
├── OAuth Client ID #2 → Onboarding Planner   (når den kommer)
└── OAuth Client ID #3 → PA                   (når den kommer)
```

**Engangs-opsætning** (sektion 0–3) gør du én gang for hele projektet.
**Pr. app** (sektion 4–5) gør du for hvert nyt værktøj — start med Check-in Planner.

---

## 0. Forudsætning — admin-rolle

Admin skal have givet dig rollen **Project Creator** (`roles/resourcemanager.projectCreator`) på `blackcapitaltechnology.com`-organisationen.

For at verificere: gå til https://console.cloud.google.com → vælg `blackcapitaltechnology.com` øverst i project-picker'en → hvis du kan se **+ NEW PROJECT** knappen, har du rollen.

## 1. Opret Google Cloud project (engangs)

1. Gå til https://console.cloud.google.com/projectcreate
2. Project name: `BCT Internal Tools`
3. **Organization:** vælg `blackcapitaltechnology.com` (vigtigt — uden denne valgmulighed kan du ikke vælge "Internal" i næste trin)
4. Location: `blackcapitaltechnology.com`
5. Klik **Create**, vent ~10 sek til projektet er klar, vælg det øverst i menubaren.

## 2. Aktivér nødvendige APIs (engangs, men tilføj flere når du har brug)

1. Sidebar → **APIs & Services** → **Library**
2. Søg `Google Calendar API` → klik **Enable**
3. Søg `Gmail API` → klik **Enable** (kræves for automatisk email når medarbejdere skal dele kalender i Check-in Planner)
4. Senere: kom tilbage og enable `Google Drive API`, etc. når andre apps kræver det. Tager 5 sek pr. API.

## 3. Konfigurér OAuth consent screen (engangs)

1. Sidebar → **APIs & Services** → **OAuth consent screen**
2. **User type:** vælg **Internal** → Create
   - Hvis "Internal" er gråt: dit project er ikke under organisationen. Slet projektet og start forfra med `blackcapitaltechnology.com` valgt som organization i trin 1.3.
3. App information:
   - App name: `BCT Internal Tools` (det her ser brugere når de logger ind på enhver af apperne)
   - User support email: `tor@blackcapitaltechnology.com`
   - App logo: spring over (valgfrit — kan tilføjes senere hvis I vil have BCT-logo på consent screen)
   - Developer contact: `tor@blackcapitaltechnology.com`
4. Save and continue
5. **Scopes:** klik **Add or remove scopes**. Tilføj alle scopes du forventer at bruge på tværs af interne værktøjer. Hver enkelt app requester kun en subset ved login, så managers ser kun de scopes appen rent faktisk bruger.
   - For Check-in Planner (start her):
     - `https://www.googleapis.com/auth/calendar.freebusy`
     - `https://www.googleapis.com/auth/calendar.events`
     - `https://www.googleapis.com/auth/gmail.send` (send vejledning til medarbejdere om kalenderdeling)
   - For Onboarding Planner (tilføj når relevant):
     - `https://www.googleapis.com/auth/calendar.events` (allerede tilføjet)
     - eventuelt `https://www.googleapis.com/auth/admin.directory.user.readonly` hvis I vil hente medarbejder-info
   - For PA (tilføj når relevant):
     - `https://www.googleapis.com/auth/gmail.readonly`
     - eller hvad PA nu skal bruge

   Klik **Update** → **Save and continue**

   **Husk:** scopes kan altid tilføjes senere — kom bare tilbage til OAuth consent screen og opdater listen. Eksisterende brugere skal genudstede consent når nye scopes kræves.

6. Test users: spring over (Internal apps har ingen test-user-grænse) → Save

---

## 4. Opret OAuth Client ID (pr. app — gør dette for Check-in Planner nu)

Der er nu to flows for Check-in Planner:
- Legacy frontend token-flow (historisk, statisk side)
- Django social-auth redirect-flow (nuværende backend-app)

Hvis du kører Django-versionen, skal redirect URIs udfyldes (se 4.6).

1. Sidebar → **APIs & Services** → **Credentials**
2. **+ Create credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Name: navngiv specifikt så du kan kende dem fra hinanden. For Check-in Planner: `Check-in Planner — Web`
5. **Authorized JavaScript origins** (klik + Add URI for hver):
   - For Check-in Planner (legacy/static): `https://tor-hash.github.io`
   - Til lokal udvikling: `http://localhost:8000` (valgfrit)
   - Render staging: `https://checkin-planner-staging.onrender.com`
   - Render prod: `https://checkin-planner-prod.onrender.com`
   - Custom domain hvis I får et: fx `https://checkin.blackcapitaltechnology.com`
6. **Authorized redirect URIs** (krævet for Django social-auth):
   - Lokal: `http://127.0.0.1:8000/auth/complete/google-oauth2/`
   - Staging: `https://checkin-planner-staging.onrender.com/auth/complete/google-oauth2/`
   - Production: `https://checkin-planner-prod.onrender.com/auth/complete/google-oauth2/`
7. Klik **Create** → kopiér **Client ID** (formatet `1234567890-abc...apps.googleusercontent.com`)

Når du senere skal tilføje Onboarding Planner: tilbage til Credentials → opret en ny OAuth Client ID med navnet `Onboarding Planner — Web` og dens egen origins-liste.

## 5. Indsæt credentials i appen (pr. app)

### Django-version (nuværende)
Sæt følgende env vars i din deploy/platform:
- `GOOGLE_OAUTH2_KEY` = Client ID
- `GOOGLE_OAUTH2_SECRET` = Client Secret
- `GOOGLE_WORKSPACE_DOMAIN` = `blackcapitaltechnology.com`

Lokal udvikling kan bruge `.env` baseret på `backend/.env.example`.

### Legacy statisk version (kun hvis stadig brugt)
`checkin-planner.html` bruger stadig `OAUTH_CLIENT_ID` konstanten i frontend token-flowet.

Client ID'et er **public** og sikkert at committe til GitHub. Client secret må derimod aldrig committes og skal kun ligge i miljøvariabler.

---

## Hvad medarbejdere skal gøre (uændret fra før)

Medarbejdere skal dele deres kalender med deres manager hvis de ikke allerede gør det:

1. Google Calendar → Settings (tandhjul) → Settings for my calendars → vælg din primære kalender
2. **Share with specific people or groups** → Add → indtast managerens email → vælg **See only free/busy (hide details)** → Send

> I Workspace er free/busy ofte allerede delt internt på domænet via en organisations-policy. Hvis det er tilfældet, behøver medarbejderen ikke gøre noget.

## Manager-flow (efter setup)

1. Åbn appen
2. Klik **Sign in with Google**
3. Vælg din `@blackcapitaltechnology.com`-konto
4. Accepter de scopes appen requester (én gang pr. app)
5. Klik **Hent free/busy**

Ingen advarselsskærm (Internal-app), ingen test user-tilføjelse, ingen Apps Script.

## Tilføj et nyt internt værktøj senere

Når Onboarding Planner eller PA skal sættes op:
1. Spring sektion 0–3 over (engangs-opsætning er klaret)
2. Hvis appen skal bruge en ny API (fx Gmail), enable den i sektion 2
3. Hvis appen kræver et nyt scope, tilføj det i sektion 3.5
4. Kør sektion 4 for den nye app (ny OAuth Client ID)
5. Kør sektion 5 for at indsætte Client ID i den nye app's kode

Hver app får sin egen Client ID, så de er fuldt isolerede på OAuth-niveau (en token udstedt til Check-in Planner kan ikke bruges af Onboarding Planner).

## Troubleshooting

- **"Internal" er gråt på OAuth consent screen** — projektet blev oprettet uden organisation. Slet og opret igen med `blackcapitaltechnology.com` som organisation.
- **"Project Creator"-knappen mangler** — admin har ikke givet dig rollen endnu. Verificér i Cloud Console → IAM & Admin → IAM (på org-niveau).
- **"redirect_uri_mismatch" / "invalid_request"** — enten JS origin eller redirect URI mangler/er forkert. Django-flow kræver præcis match på `/auth/complete/google-oauth2/`.
- **Login-vinduet lukker uden fejl, men ingen token kommer** — tredjeparts-cookies blokeres i browseren. Aktivér tredjeparts-cookies for `accounts.google.com` eller skift browser.
- **403 på en specifik medarbejders kalender** — den person har ikke delt sin kalender med den loggede-ind manager.
- **Manager udenfor `@blackcapitaltechnology.com` får "access_denied"** — Internal apps tillader kun brugere på domænet. Hvis vi skal støtte eksterne (fx konsulenter), skal projektet flyttes til External + test users (eller verification).
- **Brugeren ser "Permission denied" når en ny scope tilføjes** — eksisterende brugere skal logge ud og ind igen for at acceptere det nye scope. Klik "Log ud" i appen, så "Sign in with Google" igen.
