# Planner JS modules

Phase 5 of the robust check-in planner plan extracts the 5,200-line
`checkin-planner.html` into focused modules. Each module is loaded as a
plain `<script>` tag (no bundler yet) and registers itself with
`window.Planner.register(name, factory)` from `../app.js`.

## Currently extracted

- `oauth-signin.js` — thin wrapper around the server-side OAuth flow.
- `bookings.js` — `freeBusy` + `createBooking` + `cancelBooking` clients.

## Planned (one PR each)

- `state.js` — typed in-memory store; replaces the giant `state` global.
- `rotation-view.js` — renders the 6-week calendar grid.
- `slot-grid.js` — Mon-Fri slot picker with free/busy overlay.
- `booking-modal.js` — the modal that fires `bookings.book(...)`.
- `journal-modal.js` — entry editor; uses `PlannerApi.uploadJournalFile`.
- `people-panel.js`, `projects-panel.js` — the two sidebars.

## Conventions

- One module per file. Pure functions where possible.
- Modules don't reach into the legacy in-page `state` directly; they go
  through `state.js` once it lands.
- All HTTP goes through `window.PlannerApi` (see `../api-bridge.js`).
- No emojis in source. Keep filenames kebab-case.
