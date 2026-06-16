/* eslint-disable no-console */
/**
 * api-bridge.js
 *
 * Single thin wrapper over the Django REST endpoints exposed by
 * apps.planner.api. Every other JS module should call window.PlannerApi.*
 * rather than fetching directly so we have one place to handle CSRF, auth
 * redirects, and error normalisation.
 *
 * Server-side calendar integration: as of Phase 2 the browser no longer
 * holds OAuth tokens. freeBusy() and createBooking() proxy through Django,
 * which uses the manager's stored refresh_token to call Google.
 */
(function () {
  "use strict";

  const BASE = window.PLANNER_API_BASE || "/api";

  function getCookie(name) {
    const value = "; " + document.cookie;
    const parts = value.split("; " + name + "=");
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function csrfHeader() {
    const token = getCookie("csrftoken");
    return token ? { "X-CSRFToken": token } : {};
  }

  async function request(path, opts = {}) {
    const init = {
      method: opts.method || "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(opts.headers || {}),
        ...csrfHeader(),
      },
    };
    if (opts.body !== undefined && !(opts.body instanceof FormData)) {
      init.headers["Content-Type"] = "application/json";
      init.body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
    } else if (opts.body !== undefined) {
      init.body = opts.body;
    }

    const response = await fetch(BASE + path, init);
    if (response.status === 204) return null;
    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      body = null;
    }
    if (response.status === 401 && window.location && !(body && body.needs_consent)) {
      // Session expired — bounce back through Django login. Calendar
      // re-consent errors are returned to the caller so the UI can show
      // the specific Google permission message instead of treating the
      // request as a successful no-op.
      window.location.href = "/accounts/login/?next=" + encodeURIComponent(window.location.pathname);
      return null;
    }
    if (!response.ok) {
      const detail = (body && body.detail) || ("HTTP " + response.status);
      const error = new Error(detail);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  const PlannerApi = {
    // Aggregate state (legacy contract — useful on first boot)
    getState() {
      return request("/state");
    },
    putState(payload) {
      return request("/state/update", { method: "PUT", body: payload });
    },

    // People
    listPeople() {
      return request("/people");
    },
    createPerson(payload) {
      return request("/people", { method: "POST", body: payload });
    },
    updatePerson(personId, payload) {
      return request("/people/" + encodeURIComponent(personId), { method: "PUT", body: payload });
    },
    deletePerson(personId) {
      return request("/people/" + encodeURIComponent(personId), { method: "DELETE" });
    },

    // Projects
    listProjects() {
      return request("/projects");
    },
    createProject(payload) {
      return request("/projects", { method: "POST", body: payload });
    },
    updateProject(name, payload) {
      return request("/projects/" + encodeURIComponent(name), { method: "PUT", body: payload });
    },
    deleteProject(name) {
      return request("/projects/" + encodeURIComponent(name), { method: "DELETE" });
    },

    // Function tags
    listFunctionTags() {
      return request("/function-tags");
    },
    createFunctionTag(payload) {
      return request("/function-tags", { method: "POST", body: payload });
    },
    replaceFunctionTags(fnTags) {
      return request("/function-tags", { method: "PUT", body: { fnTags } });
    },

    // Teams
    replaceTeam(team, personIds) {
      return request("/teams/" + encodeURIComponent(team), {
        method: "PUT",
        body: { personIds },
      });
    },

    // Managers
    listManagers() {
      return request("/managers");
    },
    createManager(legacyId) {
      return request("/managers", { method: "POST", body: { id: legacyId } });
    },
    deleteManager(legacyId) {
      return request("/managers/" + encodeURIComponent(legacyId), { method: "DELETE" });
    },

    // Journal entries
    listJournalEntries(personId) {
      const qs = personId ? "?personId=" + encodeURIComponent(personId) : "";
      return request("/journal-entries" + qs);
    },
    createJournalEntry(payload) {
      return request("/journal-entries", { method: "POST", body: payload });
    },
    updateJournalEntry(entryId, payload) {
      return request("/journal-entries/" + encodeURIComponent(entryId), {
        method: "PUT",
        body: payload,
      });
    },
    deleteJournalEntry(entryId) {
      return request("/journal-entries/" + encodeURIComponent(entryId), { method: "DELETE" });
    },
    uploadJournalFile(entryId, file) {
      const fd = new FormData();
      fd.append("file", file);
      return request("/journal-entries/" + encodeURIComponent(entryId) + "/files", {
        method: "POST",
        body: fd,
      });
    },
    deleteJournalFile(entryId, fileId) {
      return request(
        "/journal-entries/" + encodeURIComponent(entryId) + "/files/" + encodeURIComponent(fileId),
        { method: "DELETE" }
      );
    },

    // Planner config + custom dates
    getConfig() {
      return request("/config");
    },
    updateConfig(payload) {
      return request("/config", { method: "PUT", body: payload });
    },
    getCustomDates() {
      return request("/custom-dates");
    },
    updateCustomDates(values) {
      return request("/custom-dates", { method: "PUT", body: { customDates: values } });
    },

    // FreeBusy + Bookings (server-side Google Calendar)
    freeBusy({ from, to, emails, team } = {}) {
      const params = new URLSearchParams();
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      if (emails && emails.length) params.set("emails", emails.join(","));
      if (team) params.set("team", team);
      return request("/freebusy?" + params.toString());
    },
    requestCalendarShare(personIds, { force = false } = {}) {
      return request("/calendar-share-requests", {
        method: "POST",
        body: { person_ids: personIds, force: !!force },
      });
    },
    getCalendarShareStatus(personIds) {
      const params = new URLSearchParams();
      params.set("person_ids", (personIds || []).join(","));
      return request("/calendar-share-requests?" + params.toString());
    },
    listBookings({ managerId, personId, status } = {}) {
      const params = new URLSearchParams();
      if (managerId) params.set("managerId", managerId);
      if (personId) params.set("personId", personId);
      if (status) params.set("status", status);
      const qs = params.toString();
      return request("/bookings" + (qs ? "?" + qs : ""));
    },
    createBooking(payload) {
      return request("/bookings", { method: "POST", body: payload });
    },
    cancelBooking(bookingId) {
      return request("/bookings/" + encodeURIComponent(bookingId), { method: "DELETE" });
    },

    // Rotation introspection
    getRotation(upcoming = 4, fromDate = null) {
      let qs = "upcoming=" + encodeURIComponent(upcoming);
      if (fromDate) {
        const d =
          fromDate instanceof Date
            ? fromDate.toISOString().slice(0, 10)
            : String(fromDate).slice(0, 10);
        qs += "&from=" + encodeURIComponent(d);
      }
      return request("/rotation?" + qs);
    },
  };

  window.PlannerApi = PlannerApi;
})();
