# Check-in Planner — local setup

A short checklist for getting the app running on your machine. Should take
~10 minutes once you have OAuth credentials in hand.

## 1. Prerequisites
- Python **3.12** (matches CI). Check: `python --version`
- Git
- A Google account on `@blackcapitaltechnology.com`
- Access to the Google Cloud Console project that owns the OAuth client
  (ask Jonas)

## 2. Clone and install
```bash
git clone https://github.com/<org>/Check-in-planner.git
cd Check-in-planner
python -m pip install -r requirements.txt
```

## 3. Create your `.env`
Copy the template:
```bash
# Windows (PowerShell)
Copy-Item backend\.env.example backend\.env

# macOS / Linux
cp backend/.env.example backend/.env
```

Open `backend/.env` and:

1. Replace `DJANGO_SECRET_KEY=change-me` with any random string. Generate one:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
2. Fill in `GOOGLE_OAUTH2_KEY` and `GOOGLE_OAUTH2_SECRET` from Google Cloud
   Console → APIs & Services → Credentials → the **Check-in Planner Local**
   OAuth client (ask Jonas if you don't have access).
3. Leave the rest as-is for local dev.

`backend/.env` is gitignored — it loads automatically when you run
`manage.py` (see `backend/manage.py` + `backend/config/{wsgi,asgi}.py`).
Real OS env vars always win over the file, so Render/CI behavior is
unaffected.

## 4. Google OAuth redirect URI
In Google Cloud Console → that same OAuth client → **Authorized redirect
URIs**, make sure this is listed:
```
http://127.0.0.1:8000/auth/complete/google-oauth2/
```
(Ask Jonas to add it if you can't edit the OAuth client.)

## 5. Database + seed data
```bash
python backend/manage.py migrate
python backend/manage.py seed_planner
```

Optional admin user for `/admin`:
```bash
python backend/manage.py createsuperuser
```

## 6. Run it
```bash
python backend/manage.py runserver
```

Open: <http://127.0.0.1:8000/accounts/login/> → sign in with your
`@blackcapitaltechnology.com` account → you'll land on the app hub at
`/home/` (links to the planner, onboarding editor, and invites).

Managers can open the onboarding flow editor at
<http://127.0.0.1:8000/onboarding/flows/>.

## 7. Onboarding API (optional, for integrations)

To exercise `/api/onboarding/*` locally, set in `backend/.env`:

```
ONBOARDING_API_TOKEN=local-dev-secret
```

Then seed the default flow:

```bash
python backend/manage.py seed_onboarding
```

## 8. Run the tests (optional but recommended)
```bash
python backend/manage.py test apps.planner.tests apps.accounts.tests apps.onboarding.tests
```

---

## Troubleshooting
- **"Only allowed Google Workspace domain can sign in."** — you're signing
  in with a non-`@blackcapitaltechnology.com` account.
- **"Your account is not on the allowlist for this app."** —
  `GOOGLE_WORKSPACE_ALLOWED_EMAILS` is set and your email isn't in it.
  Leave that var empty in `backend/.env` for local dev.
- **OAuth `redirect_uri_mismatch`** — the redirect URI in step 4 isn't
  registered on the OAuth client.
- **Static files 404** — make sure you started the server with
  `DJANGO_DEBUG=True` (default in `.env.example`).
- **`ModuleNotFoundError: dotenv`** — run
  `python -m pip install -r requirements.txt` again.
