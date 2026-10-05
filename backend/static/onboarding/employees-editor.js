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

  // Populates a <select> with every known Person (excluding `excludeId` — a
  // person can't be their own leder/buddy), preselecting `currentValue` if
  // it still points at a valid (non-excluded) person. Shared by the
  // employee-form leder/buddy selects and the "Tildel flow" dialog's.
  function populateRoleSelect(selectId, currentValue, excludeId, placeholder) {
    const sel = $(selectId);
    if (!sel) return;
    const others = people.filter((p) => p.legacy_id !== excludeId);
    const hasCurrent = !!currentValue && others.some((p) => p.legacy_id === currentValue);
    sel.innerHTML = ['<option value="">' + escapeHtml(placeholder || "— Ingen —") + "</option>"]
      .concat(
        others.map(
          (p) =>
            '<option value="' + escapeHtml(p.legacy_id) + '">' + escapeHtml(p.name || p.legacy_id) + "</option>"
        )
      )
      .join("");
    sel.value = hasCurrent ? currentValue : "";
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
    $("emp-country").value = emp.country || "DK";
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
    if (currentPerson) {
      currentPerson = people.find((p) => p.legacy_id === currentPerson.legacy_id) || currentPerson;
    }
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
          country: person.country || "DK",
        });
        // ERP ID is already known from the Person record — show it but lock it.
        $("field-emp-erp").style.display = "";
        $("emp-erp-id").readOnly = true;
        populateRoleSelect("emp-leder", person.leder_id, person.legacy_id, "— Ingen —");
        populateRoleSelect("emp-buddy", person.buddy_id, person.legacy_id, "— Ingen —");
        showEmpPanel("editor");
      } else {
        // Has OnboardingProfile → full editor + action buttons
        currentEmployee = await api.getEmployee(erpId);
        fillEmployeeForm(currentEmployee);
        populateRoleSelect("emp-leder", person.leder_id, person.legacy_id, "— Ingen —");
        populateRoleSelect("emp-buddy", person.buddy_id, person.legacy_id, "— Ingen —");
        injectActionButtons(person);
        showEmpPanel("editor");
      }
      loadDocuments(isNewEmployee ? null : erpId);

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
    $("emp-documents").classList.add("hidden");
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
    populateRoleSelect("emp-leder", null, null, "— Ingen —");
    populateRoleSelect("emp-buddy", null, null, "— Ingen —");
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
    payload.country = $("emp-country").value || "DK";
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
      // Leder/buddy live on the planner Person record, not the OnboardingProfile
      // — persisted separately via the roles endpoint (see planner.models.Person).
      let roleWarning = "";
      try {
        await api.updatePersonRoles(saved.erp_employee_id, {
          leder_id: $("emp-leder").value || null,
          buddy_id: $("emp-buddy").value || null,
        });
      } catch (err) {
        roleWarning = " Leder/buddy kunne dog ikke opdateres: " + (err.message || "ukendt fejl");
      }
      fillEmployeeForm(saved);
      await loadPeople();
      setEmpDirty(false);
      setEmpBanner("Gemt." + roleWarning, roleWarning ? "error" : "ok");
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

  function _participantLabel(token) {
    if (token === "assigning_manager") return "dig selv (den der tildeler flowet)";
    if (token === "leder" || token === "") return "medarbejderens leder";
    if (token === "buddy") return "medarbejderens buddy";
    return token; // literal email address configured on the step
  }

  // Everyone a meeting step is with. Older steps store a single with_email.
  function _meetingParticipantLabels(step) {
    const cfg = step.config || {};
    const tokens =
      Array.isArray(cfg.participants) && cfg.participants.length
        ? cfg.participants
        : [cfg.with_email || "leder"];
    return tokens.map(_participantLabel);
  }

  function describeFlowAssignment(flow, person) {
    const steps = flow.steps || [];
    const meetingSteps = steps.filter((s) => s.component_type === "calendar_meeting");
    const organizers = Array.from(new Set(meetingSteps.flatMap(_meetingParticipantLabels)));
    const name = person.name || person.legacy_id;

    let msg =
      "Når du tildeler dette flow til " + name + ", sker følgende — med det samme (Send nu) eller om morgenen på startdatoen (Send på startdatoen):\n" +
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

  // Welcome-email templates for the "Velkomstmail" select, loaded each time
  // the dialog opens (they're edited on another tab).
  let _welcomeTemplates = [];
  const _LANG_FOR_COUNTRY = { DK: "da", NO: "no" };

  function fillWelcomeEmailSelect() {
    const sel = $("assign-flow-welcome-email");
    const lang = _LANG_FOR_COUNTRY[$("assign-flow-country").value] || "da";
    const options = _welcomeTemplates.filter((t) => t.language === lang);
    sel.innerHTML = "";
    if (!options.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent =
        lang === "no"
          ? "Ingen norsk velkomstmail — den danske start-skabelon sendes"
          : "Indbygget start-skabelon";
      sel.appendChild(opt);
      return;
    }
    options.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = String(t.id);
      opt.textContent = t.name + (t.is_default ? " (standard)" : "");
      sel.appendChild(opt);
    });
    const def = options.find((t) => t.is_default) || options[0];
    sel.value = String(def.id);
  }

  async function loadWelcomeTemplates() {
    try {
      const data = await api.listWelcomeEmails();
      _welcomeTemplates = data.results || [];
    } catch (err) {
      _welcomeTemplates = [];
    }
    fillWelcomeEmailSelect();
  }

  // Live preview of the actual welcome email that will be sent — renders
  // the chosen template (or the language default / starter, see
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
    const lederId = $("assign-flow-leder").value;
    const buddyId = $("assign-flow-buddy").value;
    const leder = people.find((p) => p.legacy_id === lederId);
    const buddy = people.find((p) => p.legacy_id === buddyId);
    const templateId = $("assign-flow-welcome-email").value;
    try {
      const result = await api.previewWelcomeEmail({
        flow_slug: flowSlug,
        template_id: templateId ? parseInt(templateId, 10) : null,
        country: $("assign-flow-country").value,
        erp_id: person.legacy_id,
        leder_name: leder ? leder.name || "" : "",
        leder_email: leder ? leder.email || "" : "",
        buddy_name: buddy ? buddy.name || "" : "",
        buddy_email: buddy ? buddy.email || "" : "",
      });
      subjectEl.textContent = "Emne: " + result.subject;
      frame.srcdoc = result.html;
    } catch (err) {
      subjectEl.textContent = "Kunne ikke indlæse forhåndsvisning: " + (err.message || "ukendt fejl");
      frame.srcdoc = "";
    }
  }

  function assignFlowAction(staleperson) {
    // The button keeps the person object from when it was rendered; use the
    // freshest copy so edits saved since (start date, country, …) show up.
    const person = people.find((p) => p.legacy_id === staleperson.legacy_id) || staleperson;
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
    populateRoleSelect("assign-flow-leder", person.leder_id, person.legacy_id, "— Vælg leder —");
    populateRoleSelect("assign-flow-buddy", person.buddy_id, person.legacy_id, "— Vælg buddy —");
    // The employee's own start date — the anchor for every meeting. Empty
    // when they don't have one yet; it's required to assign.
    $("assign-flow-start-date").value = person.start_date || "";
    updateRunModeButtons();
    $("assign-flow-country").value = person.country || "DK";
    _welcomeTemplates = [];
    fillWelcomeEmailSelect();
    updateAssignFlowSummary();
    $("assign-flow-dialog").showModal();
    loadWelcomeTemplates().then(runAssignFlowPreview);
  }

  const _SLACK_REASON_LABEL = {
    not_configured: "Slack er ikke konfigureret på serveren (mangler SLACK_BOT_TOKEN).",
    no_slack_account: "Ingen Slack-konto fundet med denne e-mail.",
    error: "ukendt fejl",
  };

  function renderAutomationResult(name, automation) {
    if (!automation) {
      setEmpBanner("Flow tildelt for " + name + ".", "ok");
      return;
    }
    if (automation.deferredUntil) {
      setEmpBanner(
        name + ": Flow planlagt til " + (window.BCTDate ? window.BCTDate.format(automation.deferredUntil) : automation.deferredUntil) +
          ". Velkomstmail, Slack-invitation og mødebooking køres automatisk den dag.",
        "ok"
      );
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

    if (automation.slackInvite) {
      const s = automation.slackInvite;
      if (s.sent) {
        lines.push("Slack-invitation sendt.");
      } else if (s.reason === "not_configured") {
        lines.push("Slack-invitation sprunget over: " + _SLACK_REASON_LABEL.not_configured);
      } else {
        lines.push(
          "Slack-invitation fejlede: " +
            (s.error || _SLACK_REASON_LABEL[s.reason] || s.reason || "ukendt fejl")
        );
        hasError = true;
      }
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

  function _todayIso() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  // "Send på startdatoen" only makes sense for a start date in the future.
  function updateRunModeButtons() {
    const start = $("assign-flow-start-date").value;
    const btn = $("btn-assign-flow-on-start");
    const future = !!start && start > _todayIso();
    btn.disabled = !future;
    btn.title = future ? "" : "Vælg en startdato i fremtiden for at sende på startdatoen.";
  }

  async function confirmAssignFlow(runMode) {
    const person = _pendingAssignPerson;
    const flow = flows.find((f) => f.slug === $("assign-flow-select").value);
    if (!person || !flow) return;

    const lederId = $("assign-flow-leder").value;
    const buddyId = $("assign-flow-buddy").value;
    if (!lederId || !buddyId) {
      setEmpBanner("Leder og buddy er begge påkrævet for at tildele et flow.", "error");
      return;
    }
    const startDate = $("assign-flow-start-date").value;
    if (!startDate) {
      setEmpBanner("Startdato er påkrævet for at tildele et flow.", "error");
      return;
    }

    try {
      const result = await api.assignFlow(person.legacy_id, flow.slug, {
        leder_id: lederId,
        buddy_id: buddyId,
        start_date: startDate,
        run_mode: runMode,
        country: $("assign-flow-country").value,
        welcome_email_template_id: $("assign-flow-welcome-email").value
          ? parseInt($("assign-flow-welcome-email").value, 10)
          : null,
      });
      $("assign-flow-dialog").close();
      await loadPeople();
      // Re-open with updated status FIRST — openEmployee() unconditionally
      // clears the banner on success (setEmpBanner(null)), so rendering the
      // automation result before it would just get wiped out a moment later
      // (this is why the banner used to flash and vanish immediately).
      const updated = people.find((p) => p.legacy_id === person.legacy_id);
      if (updated) await openEmployee(updated.legacy_id);
      renderAutomationResult(person.name || person.legacy_id, result.automation);
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke tildele flow.", "error");
    }
  }

  $("assign-flow-form").addEventListener("submit", (e) => {
    e.preventDefault();
    confirmAssignFlow("now");
  });
  $("btn-assign-flow-on-start").addEventListener("click", () => {
    const form = $("assign-flow-form");
    if (!form.reportValidity()) return;
    confirmAssignFlow("on_start_date");
  });
  $("assign-flow-start-date").addEventListener("input", updateRunModeButtons);
  $("assign-flow-start-date").addEventListener("change", updateRunModeButtons);
  $("assign-flow-select").addEventListener("change", () => {
    updateAssignFlowSummary();
    runAssignFlowPreview();
  });
  $("assign-flow-country").addEventListener("change", () => {
    fillWelcomeEmailSelect();
    scheduleAssignFlowPreview();
  });
  $("assign-flow-welcome-email").addEventListener("change", scheduleAssignFlowPreview);
  $("assign-flow-leder").addEventListener("change", scheduleAssignFlowPreview);
  $("assign-flow-buddy").addEventListener("change", scheduleAssignFlowPreview);
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
      await loadPeople();
      // Same ordering fix as confirmAssignFlow: openEmployee() clears the
      // banner on success, so set it AFTER re-opening, not before.
      const updated = people.find((p) => p.legacy_id === person.legacy_id);
      if (updated) await openEmployee(updated.legacy_id);
      setEmpBanner("Flow-tildeling fjernet.", "ok");
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
    $("settings-view").classList.toggle("hidden", view !== "settings");
    $("tab-settings").classList.toggle("active", view === "settings");
    $("tab-flows").classList.toggle("active", view === "flows");
    $("tab-employees").classList.toggle("active", view === "employees");
    $("tab-welcome-email").classList.toggle("active", view === "welcome-email");
    if (view === "employees") {
      ensureEmployeesReady();
    } else if (view === "welcome-email" && window.OnboardingWelcomeEmailEditor) {
      window.OnboardingWelcomeEmailEditor.ensureReady();
    } else if (view === "settings" && window.OnboardingSettingsEditor) {
      window.OnboardingSettingsEditor.ensureReady();
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
  $("tab-settings").addEventListener("click", () => {
    if (!canLeaveCurrentTab()) return;
    switchView("settings");
  });
  // Coming back from "Giv Drive-adgang" lands on #indstillinger.
  if (window.location.hash === "#indstillinger") switchView("settings");

  // ── Documents (Google Drive) ─────────────────────────────────────────────

  function formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function renderDocuments(data) {
    const list = $("emp-documents-list");
    list.innerHTML = "";
    const folder = $("emp-documents-folder");
    if (data && data.folder_url) {
      folder.href = data.folder_url;
      folder.classList.remove("hidden");
    } else {
      folder.classList.add("hidden");
    }
    const docs = (data && data.results) || [];
    if (!docs.length) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "Ingen dokumenter uploadet endnu.";
      list.appendChild(p);
      return;
    }
    docs.forEach((d) => {
      const row = document.createElement("div");
      row.className = "doc-row";
      row.innerHTML =
        '<div><div class="doc-name"></div><p class="hint"></p></div>' +
        '<a class="btn ghost" target="_blank" rel="noopener">Åbn</a>';
      row.querySelector(".doc-name").textContent = d.name;
      row.querySelector(".hint").textContent =
        new Date(d.uploaded_at).toLocaleString("da-DK") +
        (d.uploaded_by ? " · " + d.uploaded_by : "") +
        (d.size_bytes != null ? " · " + formatSize(d.size_bytes) : "");
      const link = row.querySelector("a");
      if (d.web_view_link) link.href = d.web_view_link;
      else link.remove();
      list.appendChild(row);
    });
  }

  async function loadDocuments(erpId) {
    const section = $("emp-documents");
    if (!erpId) {
      section.classList.add("hidden");
      return;
    }
    section.classList.remove("hidden");
    $("emp-documents-status").textContent =
      "Kontrakter m.m. gemmes i medarbejderens mappe i Google Drive.";
    try {
      renderDocuments(await api.listEmployeeDocuments(erpId));
    } catch (err) {
      renderDocuments(null);
      $("emp-documents-status").textContent = err.message || "Kunne ikke hente dokumenter.";
    }
  }

  $("btn-upload-document").addEventListener("click", () => $("emp-documents-input").click());
  $("emp-documents-input").addEventListener("change", async (e) => {
    const files = e.target.files;
    const erpId = currentPerson && currentPerson.legacy_id;
    if (!files || !files.length || !erpId) return;
    const btn = $("btn-upload-document");
    btn.disabled = true;
    $("emp-documents-status").textContent =
      "Uploader " + files.length + (files.length === 1 ? " fil" : " filer") + " …";
    try {
      renderDocuments(await api.uploadEmployeeDocuments(erpId, files));
      $("emp-documents-status").textContent = "Uploadet til Google Drive.";
    } catch (err) {
      $("emp-documents-status").textContent = "";
      setEmpBanner(err.message || "Kunne ikke uploade.", "error");
    } finally {
      btn.disabled = false;
      e.target.value = "";
    }
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
    "emp-country",
    "emp-leder",
    "emp-buddy",
  ].forEach((id) => {
    const el = $(id);
    if (el) {
      el.addEventListener("input", () => setEmpDirty(true));
      el.addEventListener("change", () => setEmpDirty(true));
    }
  });
})();
