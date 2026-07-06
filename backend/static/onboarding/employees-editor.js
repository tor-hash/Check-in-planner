/* global OnboardingManageApi */
(function () {
  "use strict";

  const api = window.OnboardingManageApi;

  // people[] — all Person records from listPeople()
  // currentPerson — the lightweight person object from people[]
  // currentEmployee — the full OnboardingProfile assignment from getEmployee()
  let people = [];
  let flows = [];
  let currentPerson = null;
  let currentEmployee = null;
  let isNewEmployee = false;
  let empDirty = false;
  let employeesLoaded = false;

  const $ = (id) => document.getElementById(id);

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setEmpBanner(msg, type) {
    const el = $("banner");
    if (!msg) {
      el.classList.add("hidden");
      return;
    }
    el.textContent = msg;
    el.className = "banner " + (type || "error");
    el.classList.remove("hidden");
  }

  function setEmpDirty(v) {
    empDirty = v;
  }

  function showEmpPanel(mode) {
    $("emp-list-panel").classList.toggle("hidden", mode === "editor-only");
    $("emp-editor-panel").classList.toggle("hidden", mode !== "editor");
    $("emp-empty-state").classList.toggle("hidden", mode === "editor");
  }

  // ── Status badge (inline style — no extra CSS required) ─────────────────

  const _STATUS_LABEL = { no_flow: "Ingen flow", in_progress: "I gang", complete: "Færdig" };
  const _STATUS_COLOR = { no_flow: "#888", in_progress: "#c97b00", complete: "#2a7a2a" };

  function statusBadge(status) {
    if (!status) return "";
    const label = _STATUS_LABEL[status] || status;
    const bg = _STATUS_COLOR[status] || "#888";
    return (
      ' <span style="font-size:.72em;padding:1px 6px;border-radius:3px;' +
      "background:" +
      bg +
      ";color:#fff;vertical-align:middle;white-space:nowrap;\">" +
      escapeHtml(label) +
      "</span>"
    );
  }

  // ── Employee list ────────────────────────────────────────────────────────

  function renderEmployeeList() {
    const container = $("employee-list");
    container.innerHTML = "";
    people.forEach((p) => {
      const btn = document.createElement("button");
      btn.type = "button";
      const isActive = currentPerson && currentPerson.legacy_id === p.legacy_id;
      btn.className = "flow-card" + (isActive ? " active" : "");

      const displayName = escapeHtml(p.name || p.email || p.legacy_id);
      const teamLabel = p.team ? escapeHtml(p.team) : "<em>Ufordelt</em>";
      const badge = statusBadge(p.onboarding_status);

      btn.innerHTML =
        '<span class="name">' +
        displayName +
        "</span>" +
        '<span class="meta">' +
        escapeHtml(p.legacy_id) +
        " · " +
        teamLabel +
        badge +
        "</span>";

      btn.addEventListener("click", () => openEmployee(p.legacy_id));
      container.appendChild(btn);
    });
  }

  // ── Flow select ─────────────────────────────────────────────────────────

  function fillFlowSelect(selectedSlug) {
    const sel = $("emp-flow-slug");
    sel.innerHTML = "";
    const active = flows.filter((f) => f.is_active);
    const list = active.length ? active : flows;
    list.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.slug;
      opt.textContent = f.name + (f.is_default ? " (standard)" : "");
      if (f.slug === selectedSlug) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  // ── Dynamic action buttons ───────────────────────────────────────────────
  // Injected into .panel-head-actions; cleaned up when opening another person.

  const _ACTION_IDS = ["btn-assign-flow", "btn-remove-flow", "btn-book-meetings"];

  function clearActionButtons() {
    _ACTION_IDS.forEach((id) => {
      const el = $(id);
      if (el) el.remove();
    });
  }

  function _mkBtn(id, label, extraClass) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = id;
    btn.className = "btn " + extraClass;
    btn.textContent = label;
    return btn;
  }

  function injectActionButtons(person) {
    clearActionButtons();
    const actionsDiv = $("emp-editor-panel").querySelector(".panel-head-actions");
    if (!actionsDiv) return;
    const anchor = $("btn-save-employee"); // insert before Save

    const status = person.onboarding_status;

    if (status === "no_flow") {
      const btn = _mkBtn("btn-assign-flow", "Tildel flow", "");
      btn.addEventListener("click", () => assignFlowAction(person));
      actionsDiv.insertBefore(btn, anchor);
    }

    if (status === "in_progress") {
      const btnRemove = _mkBtn("btn-remove-flow", "Fjern flow", "danger ghost");
      btnRemove.addEventListener("click", () => removeFlowAction(person));
      actionsDiv.insertBefore(btnRemove, anchor);

      const btnBook = _mkBtn("btn-book-meetings", "Book møder", "");
      btnBook.addEventListener("click", () => bookMeetingsAction(person));
      actionsDiv.insertBefore(btnBook, anchor);
    }
  }

  // ── No-profile info panel ────────────────────────────────────────────────
  // Shown instead of the employee form when a Person has no OnboardingProfile.

  function _getOrCreateInfoPanel() {
    let info = $("emp-person-info");
    if (!info) {
      info = document.createElement("div");
      info.id = "emp-person-info";
      info.style.cssText = "padding:1rem 0;";
      // Insert before #employee-form (a direct child of #emp-editor-panel).
      // Cannot use $("emp-meta") as the reference node because emp-meta is
      // nested inside the form — insertBefore requires a direct child.
      $("emp-editor-panel").insertBefore(info, $("employee-form"));
    }
    return info;
  }

  function showPersonInfoPanel(person) {
    $("employee-form").classList.add("hidden");
    $("emp-meta").classList.add("hidden");
    $("btn-delete-employee").style.display = "none";
    $("btn-save-employee").style.display = "none";
    $("emp-editor-title").textContent = escapeHtml(person.name || person.legacy_id);

    const panel = _getOrCreateInfoPanel();
    panel.classList.remove("hidden");
    panel.innerHTML =
      "<p><strong>E-mail:</strong> " +
      escapeHtml(person.email || "—") +
      "</p>" +
      "<p><strong>Stilling:</strong> " +
      escapeHtml(person.title || "—") +
      "</p>" +
      "<p><strong>Team:</strong> " +
      escapeHtml(person.team || "Ingen team") +
      "</p>" +
      "<p class=\"hint\" style=\"margin-top:.75rem;\">" +
      "Denne person har ingen onboarding-profil og kan ikke tildeles et flow. " +
      "Opret medarbejderprofil via &ldquo;+ Ny medarbejder&rdquo; eller provisionér via API." +
      "</p>";
  }

  function hidePersonInfoPanel() {
    const info = $("emp-person-info");
    if (info) info.classList.add("hidden");
    $("employee-form").classList.remove("hidden");
    $("btn-save-employee").style.display = "";
  }

  // ── Fill form (profile-based employee) ──────────────────────────────────

  function fillEmployeeForm(emp) {
    hidePersonInfoPanel();
    $("field-emp-erp").style.display = isNewEmployee ? "" : "none";
    $("emp-erp-id").value = emp.erp_employee_id || "";
    $("emp-erp-id").readOnly = !isNewEmployee;
    $("emp-email").value = emp.email || "";
    $("emp-first-name").value = emp.first_name || "";
    $("emp-last-name").value = emp.last_name || "";
    $("emp-position").value = emp.position || "";
    $("emp-department").value = emp.department || "";
    $("emp-start-date").value = emp.start_date || "";
    fillFlowSelect(emp.flow ? emp.flow.slug : "");
    const meta = $("emp-meta");
    if (!isNewEmployee && emp.assigned_at) {
      meta.textContent =
        "Status: " +
        emp.status +
        " · Tildelt " +
        new Date(emp.assigned_at).toLocaleString("da-DK");
      meta.classList.remove("hidden");
    } else {
      meta.classList.add("hidden");
    }
    $("emp-editor-title").textContent = isNewEmployee
      ? "Ny medarbejder"
      : "Rediger medarbejder";
    $("btn-delete-employee").style.display = isNewEmployee ? "none" : "";
    $("btn-save-employee").style.display = "";
  }

  // ── Data loading ─────────────────────────────────────────────────────────

  async function loadPeople() {
    const data = await api.listPeople();
    people = data.results || [];
    renderEmployeeList();
  }

  async function loadFlowsForSelect() {
    const data = await api.listFlows();
    flows = data.results || [];
    fillFlowSelect(
      currentEmployee && currentEmployee.flow ? currentEmployee.flow.slug : ""
    );
  }

  // ── Open a person ────────────────────────────────────────────────────────

  async function openEmployee(erpId) {
    if (empDirty && !confirm("Ugemedte ændringer — forlad editor?")) return;

    const person = people.find((p) => p.legacy_id === erpId);
    if (!person) {
      setEmpBanner("Person ikke fundet.", "error");
      return;
    }

    currentPerson = person;
    currentEmployee = null;
    isNewEmployee = false;
    clearActionButtons();

    try {
      if (person.onboarding_status === null) {
        // No OnboardingProfile yet — pre-fill the form from Person data so the
        // user can create one without re-entering basic info.
        isNewEmployee = true;
        const nameParts = (person.name || "").trim().split(/\s+/);
        fillEmployeeForm({
          erp_employee_id: person.legacy_id,
          email: person.email || "",
          first_name: nameParts[0] || "",
          last_name: nameParts.slice(1).join(" ") || "",
          position: person.title || "",
          department: "",
          start_date: "",
          flow: flows.find((f) => f.is_default) || flows[0],
        });
        // ERP ID is already known from the Person record — show it but lock it.
        $("field-emp-erp").style.display = "";
        $("emp-erp-id").readOnly = true;
        showEmpPanel("editor");
      } else {
        // Has OnboardingProfile → full editor + action buttons
        currentEmployee = await api.getEmployee(erpId);
        fillEmployeeForm(currentEmployee);
        injectActionButtons(person);
        showEmpPanel("editor");
      }

      renderEmployeeList();
      setEmpDirty(false);
      setEmpBanner(null);
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke indlæse medarbejder.", "error");
    }
  }

  // ── New employee (creates OnboardingProfile) ─────────────────────────────

  function startNewEmployee() {
    if (empDirty && !confirm("Ugemedte ændringer — forlad editor?")) return;
    isNewEmployee = true;
    currentEmployee = null;
    currentPerson = null;
    clearActionButtons();
    fillEmployeeForm({
      erp_employee_id: "",
      email: "",
      first_name: "",
      last_name: "",
      position: "",
      department: "",
      start_date: "",
      flow: flows.find((f) => f.is_default) || flows[0],
    });
    showEmpPanel("editor");
    renderEmployeeList();
    setEmpDirty(true);
    setEmpBanner(null);
  }

  // ── Save employee ────────────────────────────────────────────────────────

  function readEmployeePayload() {
    const payload = {
      email: $("emp-email").value.trim(),
      first_name: $("emp-first-name").value.trim(),
      last_name: $("emp-last-name").value.trim(),
      position: $("emp-position").value.trim(),
      department: $("emp-department").value.trim(),
      flow_slug: $("emp-flow-slug").value,
    };
    const start = $("emp-start-date").value;
    payload.start_date = start || null;
    if (isNewEmployee) {
      payload.erp_employee_id = $("emp-erp-id").value.trim();
    }
    return payload;
  }

  async function saveEmployee() {
    const payload = readEmployeePayload();
    if (isNewEmployee && !payload.erp_employee_id) {
      setEmpBanner("ERP medarbejder-ID er påkrævet.", "error");
      return;
    }
    if (!payload.email) {
      setEmpBanner("E-mail er påkrævet.", "error");
      return;
    }
    if (!payload.flow_slug) {
      setEmpBanner("Vælg en onboarding-flow.", "error");
      return;
    }
    try {
      let saved;
      if (isNewEmployee) {
        saved = await api.createEmployee(payload);
        isNewEmployee = false;
        currentEmployee = saved;
        $("field-emp-erp").style.display = "none";
        $("emp-erp-id").readOnly = true;
      } else {
        const patch = { ...payload };
        delete patch.erp_employee_id;
        saved = await api.updateEmployee(currentEmployee.erp_employee_id, patch);
        currentEmployee = saved;
      }
      fillEmployeeForm(saved);
      await loadPeople();
      setEmpDirty(false);
      setEmpBanner("Gemt.", "ok");
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke gemme.", "error");
    }
  }

  // ── Delete employee ──────────────────────────────────────────────────────

  async function deleteCurrentEmployee() {
    if (!currentEmployee || isNewEmployee) return;
    if (
      !confirm(
        "Slet medarbejder " +
          currentEmployee.erp_employee_id +
          "? Dette fjerner profil og onboarding-tildeling."
      )
    )
      return;
    try {
      await api.deleteEmployee(currentEmployee.erp_employee_id);
      currentEmployee = null;
      currentPerson = null;
      clearActionButtons();
      await loadPeople();
      showEmpPanel("empty");
      setEmpDirty(false);
      setEmpBanner("Medarbejder slettet.", "ok");
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke slette.", "error");
    }
  }

  // ── Assign flow ──────────────────────────────────────────────────────────

  async function assignFlowAction(person) {
    const active = flows.filter((f) => f.is_active);
    const list = active.length ? active : flows;
    if (!list.length) {
      setEmpBanner("Ingen aktive flows tilgængelige.", "error");
      return;
    }
    const opts = list.map((f) => "  " + f.slug + "  —  " + f.name).join("\n");
    const slug = window.prompt(
      "Indtast slug for det flow du vil tildele:\n\n" + opts
    );
    if (!slug) return;

    const flow = list.find((f) => f.slug === slug.trim());
    if (!flow) {
      setEmpBanner("Flow '" + escapeHtml(slug.trim()) + "' ikke fundet.", "error");
      return;
    }

    try {
      await api.assignFlow(person.legacy_id, flow.slug);
      setEmpBanner("Flow tildelt. Kalender-delings-email er sendt.", "ok");
      await loadPeople();
      // Re-open with updated status
      const updated = people.find((p) => p.legacy_id === person.legacy_id);
      if (updated) await openEmployee(updated.legacy_id);
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke tildele flow.", "error");
    }
  }

  // ── Remove flow ──────────────────────────────────────────────────────────

  async function removeFlowAction(person) {
    if (
      !confirm(
        "Fjern onboarding-tildeling for " +
          (person.name || person.legacy_id) +
          "? Dette sletter igangværende trin."
      )
    )
      return;
    try {
      await api.removeFlow(person.legacy_id);
      setEmpBanner("Flow-tildeling fjernet.", "ok");
      await loadPeople();
      const updated = people.find((p) => p.legacy_id === person.legacy_id);
      if (updated) await openEmployee(updated.legacy_id);
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke fjerne flow.", "error");
    }
  }

  // ── Book calendar meetings ───────────────────────────────────────────────

  async function bookMeetingsAction(person) {
    if (
      !confirm(
        "Book kalender-møder for " +
          (person.name || person.legacy_id) +
          "? Alle afventende møde-trin i det aktive flow bookes nu."
      )
    )
      return;
    try {
      const result = await api.bookCalendarMeetings(person.legacy_id);
      const nBooked = result.booked ? result.booked.length : 0;
      const nFailed = result.failed ? result.failed.length : 0;
      if (nBooked === 0 && nFailed === 0) {
        setEmpBanner("Ingen afventende kalender-trin fundet.", "ok");
      } else if (nFailed === 0) {
        setEmpBanner(nBooked + " møde(r) booket.", "ok");
      } else {
        const firstError =
          result.failed[0] && result.failed[0].error ? " — " + result.failed[0].error : "";
        setEmpBanner(
          nBooked + " booket, " + nFailed + " fejlede" + firstError + ".",
          nBooked > 0 ? "ok" : "error"
        );
      }
      await loadPeople();
    } catch (err) {
      setEmpBanner(err.message || "Booking fejlede.", "error");
    }
  }

  // ── Ensure employees tab is loaded ───────────────────────────────────────

  async function ensureEmployeesReady() {
    if (employeesLoaded) return;
    try {
      await loadFlowsForSelect();
      await loadPeople();
      employeesLoaded = true;
      showEmpPanel("empty");
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke indlæse medarbejdere.", "error");
    }
  }

  // ── View switching ───────────────────────────────────────────────────────

  function switchView(view) {
    const isFlows = view === "flows";
    $("flows-view").classList.toggle("hidden", !isFlows);
    $("employees-view").classList.toggle("hidden", isFlows);
    $("tab-flows").classList.toggle("active", isFlows);
    $("tab-employees").classList.toggle("active", !isFlows);
    if (!isFlows) {
      ensureEmployeesReady();
    }
  }

  // ── Event listeners ──────────────────────────────────────────────────────

  $("tab-flows").addEventListener("click", () => {
    if (empDirty && !confirm("Ugemedte ændringer — skift fane?")) return;
    switchView("flows");
  });
  $("tab-employees").addEventListener("click", () => switchView("employees"));

  $("btn-new-employee").addEventListener("click", startNewEmployee);

  $("btn-emp-back-list").addEventListener("click", () => {
    if (empDirty && !confirm("Ugemedte ændringer — forlad editor?")) return;
    currentEmployee = null;
    currentPerson = null;
    clearActionButtons();
    hidePersonInfoPanel();
    showEmpPanel("empty");
    renderEmployeeList();
    setEmpDirty(false);
  });

  $("btn-save-employee").addEventListener("click", saveEmployee);
  $("btn-delete-employee").addEventListener("click", deleteCurrentEmployee);

  [
    "emp-erp-id",
    "emp-email",
    "emp-first-name",
    "emp-last-name",
    "emp-position",
    "emp-department",
    "emp-start-date",
    "emp-flow-slug",
  ].forEach((id) => {
    const el = $(id);
    if (el) {
      el.addEventListener("input", () => setEmpDirty(true));
      el.addEventListener("change", () => setEmpDirty(true));
    }
  });
})();
