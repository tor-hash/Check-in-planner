/* global OnboardingManageApi */
(function () {
  "use strict";

  const api = window.OnboardingManageApi;
  let employees = [];
  let flows = [];
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

  function renderEmployeeList() {
    const container = $("employee-list");
    container.innerHTML = "";
    employees.forEach((e) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "flow-card" +
        (currentEmployee && currentEmployee.erp_employee_id === e.erp_employee_id
          ? " active"
          : "");
      const name =
        [e.first_name, e.last_name].filter(Boolean).join(" ") || e.email;
      btn.innerHTML =
        '<span class="name">' +
        escapeHtml(name) +
        "</span>" +
        '<span class="meta">' +
        escapeHtml(e.erp_employee_id) +
        " · " +
        escapeHtml((e.flow && e.flow.name) || "—") +
        " · " +
        escapeHtml(e.status || "") +
        "</span>";
      btn.addEventListener("click", () => openEmployee(e.erp_employee_id));
      container.appendChild(btn);
    });
  }

  function fillEmployeeForm(emp) {
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
  }

  async function loadEmployees() {
    const data = await api.listEmployees();
    employees = data.results || [];
    renderEmployeeList();
  }

  async function loadFlowsForSelect() {
    const data = await api.listFlows();
    flows = data.results || [];
    fillFlowSelect(currentEmployee && currentEmployee.flow ? currentEmployee.flow.slug : "");
  }

  async function openEmployee(erpId) {
    if (empDirty && !confirm("Ugemedte ændringer — forlad editor?")) return;
    try {
      currentEmployee = await api.getEmployee(erpId);
      isNewEmployee = false;
      fillEmployeeForm(currentEmployee);
      showEmpPanel("editor");
      renderEmployeeList();
      setEmpDirty(false);
      setEmpBanner(null);
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke indlæse medarbejder.", "error");
    }
  }

  function startNewEmployee() {
    if (empDirty && !confirm("Ugemedte ændringer — forlad editor?")) return;
    isNewEmployee = true;
    currentEmployee = null;
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
      await loadEmployees();
      renderEmployeeList();
      setEmpDirty(false);
      setEmpBanner("Gemt.", "ok");
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke gemme.", "error");
    }
  }

  async function deleteCurrentEmployee() {
    if (!currentEmployee || isNewEmployee) return;
    if (
      !confirm(
        "Slet medarbejder " +
          currentEmployee.erp_employee_id +
          "? Dette fjerner profil og onboarding-tildeling."
      )
    ) {
      return;
    }
    try {
      await api.deleteEmployee(currentEmployee.erp_employee_id);
      currentEmployee = null;
      await loadEmployees();
      showEmpPanel("empty");
      renderEmployeeList();
      setEmpDirty(false);
      setEmpBanner("Medarbejder slettet.", "ok");
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke slette.", "error");
    }
  }

  async function ensureEmployeesReady() {
    if (employeesLoaded) return;
    try {
      await loadFlowsForSelect();
      await loadEmployees();
      employeesLoaded = true;
      showEmpPanel("empty");
    } catch (err) {
      setEmpBanner(err.message || "Kunne ikke indlæse medarbejdere.", "error");
    }
  }

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

  $("tab-flows").addEventListener("click", () => {
    if (empDirty && !confirm("Ugemedte ændringer — skift fane?")) return;
    switchView("flows");
  });
  $("tab-employees").addEventListener("click", () => switchView("employees"));

  $("btn-new-employee").addEventListener("click", startNewEmployee);
  $("btn-emp-back-list").addEventListener("click", () => {
    if (empDirty && !confirm("Ugemedte ændringer — forlad editor?")) return;
    currentEmployee = null;
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
