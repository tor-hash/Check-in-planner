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

  // Note: employees are never created with a flow attached (creation and
  // flow-attachment are deliberately decoupled — see services.py). The
  // "+ Ny medarbejder" form below has no flow picker; attaching a flow is
  // done afterwards via the "Tildel flow" action button, which fills
  // #assign-flow-select directly in assignFlowAction() further down.

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
  // Attaching a flow triggers, all at once: a welcome email (with the
  // onboarding steps) + calendar-share request to the employee, and an
  // attempt to book every calendar_meeting step. The dialog below shows a
  // plain-language summary of that before the manager confirms.

  let _pendingAssignPerson = null;

  function _meetingOrganizerLabel(step) {
    const email = (step.config && step.config.with_email) || "";
    if (email === "assigning_manager") return "dig selv (den der tildeler flowet)";
    return email || "ukendt organisator";
  }

  function describeFlowAssignment(flow, person) {
    const steps = flow.steps || [];
    const meetingSteps = steps.filter((s) => s.component_type === "calendar_meeting");
    const organizers = Array.from(new Set(meetingSteps.map(_meetingOrganizerLabel)));
    const name = person.name || person.legacy_id;

    let msg =
      "Når du tildeler dette flow til " + name + ", sker følgende med det samme:\n" +
      "- " + name + " får en velkomstmail med onboarding-trinnene og en anmodning om at dele sin kalender.\n";

    if (meetingSteps.length > 0) {
      msg +=
        "- Vi forsøger at booke " + meetingSteps.length +
        (meetingSteps.length === 1 ? " møde" : " møder") +
        (organizers.length ? " med " + organizers.join(", ") : "") + ".";
    } else {
      msg += "- Dette flow har ingen møder at booke.";
    }
    return msg;
  }

  function updateAssignFlowSummary() {
    const sel = $("assign-flow-select");
    const flow = flows.find((f) => f.slug === sel.value);
    $("assign-flow-summary").textContent =
      flow && _pendingAssignPerson ? describeFlowAssignment(flow, _pendingAssignPerson) : "";
  }

  // Live preview of the actual welcome email that will be sent — renders
  // the flow's resolved template (own / inherited default / starter, see
  // welcome_email.py) against this person's real data + whatever buddy
  // fields are currently typed in. Debounced so typing doesn't spam the
  // server; this is the "preview-before-send" step — no separate button,
  // it just stays live while the dialog is open.
  let _assignPreviewTimer = null;

  function scheduleAssignFlowPreview() {
    clearTimeout(_assignPreviewTimer);
    _assignPreviewTimer = setTimeout(runAssignFlowPreview, 350);
  }

  async function runAssignFlowPreview() {
    const person = _pendingAssignPerson;
    const flowSlug = $("assign-flow-select").value;
    const subjectEl = $("assign-flow-preview-subject");
    const frame = $("assign-flow-preview-frame");
    if (!person || !flowSlug) {
      subjectEl.textContent = "";
      frame.srcdoc = "";
      return;
    }
    subjectEl.textContent = "Indlæser forhåndsvisning …";
    try {
      const result = await api.previewWelcomeEmail(flowSlug, {
        erp_id: person.legacy_id,
        buddy_name: $("assign-flow-buddy-name").value.trim(),
        buddy_email: $("assign-flow-buddy-email").value.trim(),
      });
      subjectEl.textContent = "Emne: " + result.subject;
      frame.srcdoc = result.html;
    } catch (err) {
      subjectEl.textContent = "Kunne ikke indlæse forhåndsvisning: " + (err.message || "ukendt fejl");
      frame.srcdoc = "";
    }
  }

  function assignFlowAction(person) {
    const active = flows.filter((f) => f.is_active);
    const list = active.length ? active : flows;
    if (!list.length) {
      setEmpBanner("Ingen aktive flows tilgængelige.", "error");
      return;
    }

    _pendingAssignPerson = person;
    const sel = $("assign-flow-select");
    sel.innerHTML = "";
    list.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.slug;
      opt.textContent = f.name + (f.is_default ? " (standard)" : "");
      sel.appendChild(opt);
    });
    $("assign-flow-buddy-name").value = "";
    $("assign-flow-buddy-email").value = "";
    updateAssignFlowSummary();
    runAssignFlowPreview();
    $("assign-flow-dialog").showModal();
  }

  function renderAutomationResult(name, automation) {
    if (!automation) {
      setEmpBanner("Flow tildelt for " + name + ".", "ok");
      return;
    }
    const lines = [];
    let hasError = false;

    if (automation.welcomeEmail) {
      lines.push(
        automation.welcomeEmail.sent
          ? "Velkomstmail sendt."
          : "Velkomstmail fejlede: " + (automation.welcomeEmail.error || "ukendt fejl")
      );
      if (!automation.welcomeEmail.sent) hasError = true;
    }

    if (automation.meetings) {
      const m = automation.meetings;
      const nBooked = m.booked ? m.booked.length : 0;
      const nFailed = m.failed ? m.failed.length : 0;
      if (m.error) {
        lines.push("Møde-booking: " + m.error);
        hasError = true;
      } else if (nBooked === 0 && nFailed === 0) {
        lines.push("Ingen møder at booke.");
      } else {
        lines.push(nBooked + " møde(r) booket" + (nFailed ? ", " + nFailed + " fejlede" : "") + ".");
        if (nFailed) {
          hasError = true;
          m.failed.forEach((f) => {
            lines.push("  - " + f.stepTitle + ": " + (f.error || "ukendt fejl"));
          });
        }
      }
    }

    setEmpBanner(name + ":\n" + lines.join("\n"), hasError ? "error" : "ok");
  }

  async function confirmAssignFlow() {
    const person = _pendingAssignPerson;
    const flow = flows.find((f) => f.slug === $("assign-flow-select").value);
    if (!person || !flow) return;

    try {
      const result = await api.assignFlow(person.legacy_id, flow.slug, {
        buddy_name: $("assign-flow-buddy-name").value.trim(),
        buddy_email: $("assign-flow-buddy-email").value.trim(),
      });
      $("assign-flow-dialog").close();
      await loadPeople();
      renderAutomationResult(person.name || person.legacy_id, result.automation);
      // Re-open with updated status
      const updated = people.find((p) => p.legacy_id === person.legacy_id);
      if (updated) await openEmployee(updated.legacy_id);
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke tildele flow.", "error");
    }
  }

  $("assign-flow-form").addEventListener("submit", (e) => {
    e.preventDefault();
    confirmAssignFlow();
  });
  $("assign-flow-select").addEventListener("change", () => {
    updateAssignFlowSummary();
    runAssignFlowPreview();
  });
  $("assign-flow-buddy-name").addEventListener("input", scheduleAssignFlowPreview);
  $("assign-flow-buddy-email").addEventListener("input", scheduleAssignFlowPreview);
  $("btn-assign-flow-cancel").addEventListener("click", () => {
    $("assign-flow-dialog").close();
    _pendingAssignPerson = null;
  });

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
      renderAutomationResult(person.name || person.legacy_id, { meetings: result });
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
  // Three views share this switcher: "flows" (flows-editor.js),
  // "employees" (this file), "welcome-email" (welcome-email-editor.js).
  // Each non-flows view lazy-loads itself the first time it's shown via
  // ensureEmployeesReady() / window.OnboardingWelcomeEmailEditor.ensureReady().

  function switchView(view) {
    $("flows-view").classList.toggle("hidden", view !== "flows");
    $("employees-view").classList.toggle("hidden", view !== "employees");
    $("welcome-email-view").classList.toggle("hidden", view !== "welcome-email");
    $("tab-flows").classList.toggle("active", view === "flows");
    $("tab-employees").classList.toggle("active", view === "employees");
    $("tab-welcome-email").classList.toggle("active", view === "welcome-email");
    if (view === "employees") {
      ensureEmployeesReady();
    } else if (view === "welcome-email" && window.OnboardingWelcomeEmailEditor) {
      window.OnboardingWelcomeEmailEditor.ensureReady();
    }
  }

  // ── Event listeners ──────────────────────────────────────────────────────

  function canLeaveCurrentTab() {
    if (empDirty && !confirm("Ugemedte ændringer — skift fane?")) return false;
    if (window.OnboardingWelcomeEmailEditor && window.OnboardingWelcomeEmailEditor.isDirty()) {
      return confirm("Ugemedte ændringer til velkomstmailen — skift fane?");
    }
    return true;
  }

  $("tab-flows").addEventListener("click", () => {
    if (!canLeaveCurrentTab()) return;
    switchView("flows");
  });
  $("tab-employees").addEventListener("click", () => {
    if (!canLeaveCurrentTab()) return;
    switchView("employees");
  });
  $("tab-welcome-email").addEventListener("click", () => {
    if (!canLeaveCurrentTab()) return;
    switchView("welcome-email");
  });

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
  ].forEach((id) => {
    const el = $(id);
    if (el) {
      el.addEventListener("input", () => setEmpDirty(true));
      el.addEventListener("change", () => setEmpDirty(true));
    }
  });
})();
