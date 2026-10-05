/* global window */
(function () {
  "use strict";

  const BASE = window.ONBOARDING_API_BASE || "/api/onboarding/manage";

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
    if (opts.body instanceof FormData) {
      init.body = opts.body; // browser sets the multipart Content-Type + boundary
    } else if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
    }

    const response = await fetch(BASE + path, init);
    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      body = null;
    }
    if (response.status === 401 && window.location) {
      window.location.href =
        "/accounts/login/?next=" + encodeURIComponent(window.location.pathname);
      return null;
    }
    if (!response.ok) {
      const detail = (body && body.detail) || "HTTP " + response.status;
      const error = new Error(detail);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  window.OnboardingManageApi = {
    listComponentTypes() {
      return request("/component-types");
    },
    listFlows() {
      return request("/flows");
    },
    getFlow(slug) {
      return request("/flows/" + encodeURIComponent(slug));
    },
    createFlow(payload) {
      return request("/flows", { method: "POST", body: payload });
    },
    updateFlow(slug, payload) {
      return request("/flows/" + encodeURIComponent(slug), { method: "PATCH", body: payload });
    },
    deleteFlow(slug) {
      return request("/flows/" + encodeURIComponent(slug), { method: "DELETE" });
    },
    createStep(slug, payload) {
      return request("/flows/" + encodeURIComponent(slug) + "/steps", {
        method: "POST",
        body: payload,
      });
    },
    updateStep(slug, stepId, payload) {
      return request(
        "/flows/" + encodeURIComponent(slug) + "/steps/" + stepId,
        { method: "PATCH", body: payload }
      );
    },
    deleteStep(slug, stepId) {
      return request(
        "/flows/" + encodeURIComponent(slug) + "/steps/" + stepId,
        { method: "DELETE" }
      );
    },
    reorderSteps(slug, stepIds) {
      return request("/flows/" + encodeURIComponent(slug) + "/steps/reorder", {
        method: "PUT",
        body: { step_ids: stepIds },
      });
    },
    listEmployees() {
      return request("/employees");
    },
    getEmployee(erpId) {
      return request("/employees/" + encodeURIComponent(erpId));
    },
    createEmployee(payload) {
      return request("/employees", { method: "POST", body: payload });
    },
    updateEmployee(erpId, payload) {
      return request("/employees/" + encodeURIComponent(erpId), {
        method: "PATCH",
        body: payload,
      });
    },
    deleteEmployee(erpId) {
      return request("/employees/" + encodeURIComponent(erpId), { method: "DELETE" });
    },

    // ── People (all Person records with team + onboarding status) ──────────
    listPeople() {
      return request("/people");
    },
    updatePersonRoles(legacyId, payload) {
      return request("/people/" + encodeURIComponent(legacyId) + "/roles", {
        method: "PATCH",
        body: payload,
      });
    },
    assignFlow(erpId, flowSlug, extra) {
      return request("/employees/" + encodeURIComponent(erpId) + "/assign-flow", {
        method: "POST",
        body: { flow_slug: flowSlug, ...(extra || {}) },
      });
    },
    removeFlow(erpId) {
      return request("/employees/" + encodeURIComponent(erpId) + "/assign-flow", {
        method: "DELETE",
      });
    },
    bookCalendarMeetings(erpId) {
      return request("/employees/" + encodeURIComponent(erpId) + "/book-calendar-meetings", {
        method: "POST",
      });
    },

    // ── Settings ("Indstillinger" tab) + employee documents (Google Drive) ──
    getSettings() {
      return request("/settings");
    },
    saveSettings(payload) {
      return request("/settings", { method: "PUT", body: payload });
    },
    listEmployeeDocuments(erpId) {
      return request("/employees/" + encodeURIComponent(erpId) + "/documents");
    },
    uploadEmployeeDocuments(erpId, files) {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("file", f));
      return request("/employees/" + encodeURIComponent(erpId) + "/documents", {
        method: "POST",
        body: form,
      });
    },

    // ── Welcome email library ("Velkomstmail" tab) ──────────────────────────
    listWelcomeEmails() {
      return request("/welcome-emails");
    },
    createWelcomeEmail(payload) {
      return request("/welcome-emails", { method: "POST", body: payload });
    },
    updateWelcomeEmail(id, payload) {
      return request("/welcome-emails/" + encodeURIComponent(id), { method: "PUT", body: payload });
    },
    deleteWelcomeEmail(id) {
      return request("/welcome-emails/" + encodeURIComponent(id), { method: "DELETE" });
    },
    // payload: {subject+html_body (draft) | template_id, country, flow_slug,
    //           erp_id, leder_name, leder_email, buddy_name, buddy_email}
    previewWelcomeEmail(payload) {
      return request("/welcome-emails/preview", { method: "POST", body: payload || {} });
    },
  };
})();
