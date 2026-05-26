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
    if (opts.body !== undefined) {
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
  };
})();
