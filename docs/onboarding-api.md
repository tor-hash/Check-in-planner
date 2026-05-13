# Onboarding API

A headless REST API for creating new-hire onboarding flows and tracking
their progress. Designed to be called by:

- **ERP** — creates the employee when a hire is finalised in HR.
- **HR tooling / portal** — reads flow state and marks steps complete.

Onboardees themselves never log in to this system. They are stored as
inactive Django users (`is_active=False`) so they cannot reach the
check-in planner.

## Auth

Every endpoint requires header

```
X-API-Key: <ONBOARDING_API_TOKEN>
```

The token is a single shared secret read from the env var
`ONBOARDING_API_TOKEN`. Responses:

| Condition | Status |
| --- | --- |
| Token unset on the server | 503 |
| Header missing | 401 |
| Header wrong | 403 |
| Header correct | request proceeds |

Use a long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

CSRF is disabled on these endpoints (they're service-to-service).

## Endpoints

Base path: `/api/onboarding/`

### `POST /employees`

Create or upsert an employee. **Idempotent on `erp_employee_id`** — a
replay returns the existing assignment with status `200`; a first-time
call returns `201`.

Request body:
```json
{
  "erp_employee_id": "E1234",
  "email": "jane@blackcapitaltechnology.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "position": "Backend dev",
  "department": "Tech",
  "start_date": "2026-06-01",
  "flow_slug": "default"
}
```

- `erp_employee_id` (required) — your ERP's stable identifier.
- `email` (required) — used to create the Django user (inactive).
- `flow_slug` (optional) — pick a specific flow. Omitted → the flow with
  `is_default=True`.
- All other fields optional.

Response: the same shape as `GET /employees/{erp_id}` below.

### `GET /employees`

Paginated list of all assignments. Query params:
- `page` (default 1)
- `page_size` (default 25, max 100)

Response:
```json
{
  "count": 12, "page": 1, "page_size": 25, "num_pages": 1,
  "results": [ { ...assignment payload... } ]
}
```

### `GET /employees/{erp_employee_id}`

Full assignment payload:
```json
{
  "erp_employee_id": "E1234",
  "email": "jane@blackcapitaltechnology.com",
  "first_name": "Jane", "last_name": "Doe",
  "position": "Backend dev", "department": "Tech", "start_date": "2026-06-01",
  "status": "in_progress",
  "assigned_at": "2026-05-12T09:00:00+00:00",
  "started_at": "2026-05-12T09:05:00+00:00",
  "completed_at": null,
  "flow": {"slug": "default", "name": "BCT onboarding", "description": "..."},
  "steps": [
    {
      "id": 7, "order": 1, "component_type": "info_link",
      "title": "Read handbook", "description": "...",
      "config": {"url": "https://...", "body": "...", "requires_read": true},
      "is_required": true,
      "status": "completed",
      "completion_data": {"read_at": "2026-05-12T09:05:00+00:00"},
      "completed_at": "2026-05-12T09:05:00+00:00",
      "completed_by": "hr-portal"
    },
    ...
  ]
}
```

Status codes:
- `200` — success
- `404` — no employee with this `erp_employee_id`

### `PATCH /employees/{erp_employee_id}/steps/{step_id}`

Update a single step's progress.

Request body:
```json
{
  "status": "completed",
  "completion_data": {"checked": true},
  "completed_by": "hr-portal"
}
```

- `status` (required): one of `pending` (re-open), `completed`, `skipped`.
- `completion_data` (required dict): validated against the step's component
  type — see *Component types* below.
- `completed_by` (optional): free-form tag of the source system. Stored
  for audit; not validated.

On `completed`/`skipped`, the assignment status is recomputed:
- First finished step flips assignment from `pending` → `in_progress`.
- All required steps finished flips it to `completed`.
- Re-opening (`pending`) reverts the assignment if it was `completed`.

Response:
```json
{
  "assignment_status": "in_progress",
  "step": {
    "id": 7, "order": 1, "title": "...", "component_type": "checkbox",
    "status": "completed",
    "completion_data": {"checked": true},
    "completed_at": "2026-05-12T09:05:00+00:00",
    "completed_by": "hr-portal"
  }
}
```

Status codes:
- `200` — success
- `400` — invalid payload or `completion_data` doesn't match the component schema
- `404` — unknown employee, or step doesn't belong to this employee's flow

### `GET /flows` and `GET /flows/{slug}`

Read flow templates (without an employee). Useful for tooling that
renders a step-by-step preview before an employee exists.

## Component types

The set of step component types is **fixed in code** (`apps/onboarding/components.py`).
Each defines a config schema (stored on `FlowStep.config`) and a
completion schema (validated on PATCH).

### `info_link`
Config:
```json
{"body": "Optional intro text.", "url": "https://...", "requires_read": true}
```
Completion: `{"read_at": "2026-05-12T09:05:00+00:00"}` (optional). Empty
`{}` also accepted.

### `checkbox`
Config: `{"label": "Photo taken?"}`

Completion: `{"checked": true}` (required `bool`).

### `form`
Config:
```json
{
  "fields": [
    {"name": "tax_number", "label": "Tax #", "type": "text", "required": true},
    {"name": "country", "label": "Country", "type": "text", "required": true}
  ]
}
```
Field types: `text`, `longtext`, `email`, `number`, `date`, `boolean`.

Completion: `{"values": {"tax_number": "...", "country": "..."}}`.

### `calendar_meeting`
Passive metadata; this app does NOT create the calendar event itself.
HR tooling schedules the meeting elsewhere and PATCHes the result back.

Config:
```json
{"with_email": "manager@...", "duration_minutes": 30, "suggested_window": "first week"}
```
Completion:
```json
{
  "scheduled_at": "2026-06-01T10:00:00+02:00",
  "google_event_id": "abc123",
  "html_link": "https://calendar.google.com/event?eid=..."
}
```
`scheduled_at` (ISO datetime string) is required; the rest are optional.

## Admin

Manager/admin users build flows via Django admin at `/admin/onboarding/`.
The flow inline (`FlowStepInline`) lets you add/edit/reorder steps in one
screen. Step configs are JSON; the admin form runs the component
validator so bad config is rejected before save.

Seed the default flow with example steps:
```
python backend/manage.py seed_onboarding
```

## Example calls

```bash
TOKEN=...  # match ONBOARDING_API_TOKEN
BASE=https://checkin-planner-prod.onrender.com/api/onboarding

# 1. ERP creates an employee on hire-finalisation
curl -X POST "$BASE/employees" \
  -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "erp_employee_id":"E1234",
    "email":"jane@blackcapitaltechnology.com",
    "first_name":"Jane","last_name":"Doe",
    "position":"Backend dev","department":"Tech",
    "start_date":"2026-06-01"
  }'

# 2. HR portal fetches the flow + progress
curl "$BASE/employees/E1234" -H "X-API-Key: $TOKEN"

# 3. HR portal marks "photo taken" complete
curl -X PATCH "$BASE/employees/E1234/steps/8" \
  -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"completed","completion_data":{"checked":true},"completed_by":"hr-portal"}'
```

## Operational notes

- The Django user created for the onboardee is `is_active=False` with an
  unusable password. They cannot sign in to anything in this project.
- Editing a flow template (`OnboardingFlow` / `FlowStep`) does NOT
  retro-apply to in-flight assignments — existing `StepProgress` rows
  keep pointing at their original step. Pick "add new step at end" if
  you need to extend an in-flight onboarding.
- The shared API token is a single value in `ONBOARDING_API_TOKEN`. For
  per-client tokens or scopes, this can later be replaced by a small
  `ServiceClient` model (one row per integration) without changing the
  endpoint shapes.
