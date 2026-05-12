/* eslint-disable no-console */
/**
 * modules/oauth-signin.js
 *
 * Phase 2 + 5: the browser no longer needs to mint Google tokens — Django
 * holds the manager's refresh_token and calls Calendar API server-side.
 * This module reduces the OAuth surface in the browser to: "are we signed
 * in?" and "go (re-)consent if needed".
 *
 * The signed-in state is whatever Django's session cookie gives us (the
 * standard `/accounts/login/` flow with social-auth-app-django). When a
 * server endpoint replies 401 with `needs_consent: true`, we redirect the
 * user back through the OAuth re-consent flow so we get a fresh token.
 */
(function () {
  "use strict";

  if (!window.Planner || typeof window.Planner.register !== "function") {
    return;
  }

  window.Planner.register("oauthSignin", function (api) {
    function reconsent() {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = "/auth/login/google-oauth2/?next=" + next;
    }

    async function ensureCalendarAccess() {
      try {
        // Cheap probe: ask for an empty freeBusy window. If we get a 401
        // with needs_consent the api-bridge will throw; we surface it here.
        const now = new Date().toISOString();
        const inOneHour = new Date(Date.now() + 60 * 60 * 1000).toISOString();
        await api.freeBusy({ from: now, to: inOneHour, emails: [window.PLANNER_USER_EMAIL] });
        return true;
      } catch (err) {
        if (err && err.status === 401 && err.body && err.body.needs_consent) {
          if (confirm("Google Calendar access er udlobet. Log ind igen?")) {
            reconsent();
          }
          return false;
        }
        throw err;
      }
    }

    return { reconsent, ensureCalendarAccess };
  });
})();
