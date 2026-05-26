/* global OnboardingManageApi */
(function () {
  "use strict";

  const api = window.OnboardingManageApi;
  let componentTypes = [];
  let flows = [];
  let currentFlow = null;
  let isNewFlow = false;
  let dirty = false;
  let editingStepId = null;

  const $ = (id) => document.getElementById(id);

  function setBanner(msg, type) {
    const el = $("banner");
    if (!msg) {
      el.classList.add("hidden");
      return;
    }
    el.textContent = msg;
    el.className = "banner " + (type || "error");
    el.classList.remove("hidden");
  }

  function setDirty(v) {
    dirty = v;
  }

  window.addEventListener("beforeunload", (e) => {
    if (dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  function showPanel(mode) {
    $("list-panel").classList.toggle("hidden", mode === "editor-only");
    $("editor-panel").classList.toggle("hidden", mode !== "editor");
    $("empty-state").classList.toggle("hidden", mode === "editor");
  }

  function renderFlowList() {
    const container = $("flow-list");
    container.innerHTML = "";
    flows.forEach((f) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "flow-card" + (currentFlow && currentFlow.slug === f.slug ? " active" : "");
      const badges = [];
      if (f.is_default) badges.push('<span class="badge">Standard</span>');
      if (!f.is_active) badges.push('<span class="badge inactive">Inaktiv</span>');
      btn.innerHTML =
        '<span class="name">' +
        escapeHtml(f.name) +
        "</span>" +
        '<span class="meta">' +
        badges.join("") +
        escapeHtml(f.slug) +
        " · " +
        (f.steps ? f.steps.length : 0) +
        " trin" +
        (f.assignment_count != null ? " · " + f.assignment_count + " tildelinger" : "") +
        "</span>";
      btn.addEventListener("click", () => openFlow(f.slug));
      container.appendChild(btn);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fillFlowForm(flow) {
    $("field-slug").style.display = isNewFlow ? "" : "none";
    $("flow-slug").value = flow.slug || "";
    $("flow-slug").disabled = !isNewFlow;
    $("flow-name").value = flow.name || "";
    $("flow-description").value = flow.description || "";
    $("flow-default").checked = !!flow.is_default;
    $("flow-active").checked = flow.is_active !== false;
    $("editor-title").textContent = isNewFlow ? "Ny flow" : "Rediger: " + flow.name;
    $("btn-delete-flow").style.display = isNewFlow ? "none" : "";
  }

  function renderSteps() {
    const container = $("steps-list");
    container.innerHTML = "";
    if (!currentFlow || !currentFlow.steps) return;
    const sorted = [...currentFlow.steps].sort((a, b) => a.order - b.order);
    sorted.forEach((step, idx) => {
      const row = document.createElement("div");
      row.className = "step-row";
      row.innerHTML =
        '<div class="order">' +
        step.order +
        '</div><div><div class="title">' +
        escapeHtml(step.title) +
        '</div><div class="type">' +
        escapeHtml(step.component_type) +
        (step.is_required ? "" : " · valgfri") +
        "</div></div>";
      const actions = document.createElement("div");
      actions.className = "step-actions";

      const up = document.createElement("button");
      up.type = "button";
      up.className = "btn ghost";
      up.textContent = "↑";
      up.disabled = idx === 0;
      up.addEventListener("click", () => moveStep(step.id, -1));

      const down = document.createElement("button");
      down.type = "button";
      down.className = "btn ghost";
      down.textContent = "↓";
      down.disabled = idx === sorted.length - 1;
      down.addEventListener("click", () => moveStep(step.id, 1));

      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "btn ghost";
      edit.textContent = "Rediger";
      edit.addEventListener("click", () => openStepDialog(step));

      const del = document.createElement("button");
      del.type = "button";
      del.className = "btn ghost danger";
      del.textContent = "Slet";
      del.addEventListener("click", () => removeStep(step.id));

      actions.append(up, down, edit, del);
      row.appendChild(actions);
      container.appendChild(row);
    });
  }

  async function moveStep(stepId, direction) {
    if (!currentFlow) return;
    const sorted = [...currentFlow.steps].sort((a, b) => a.order - b.order);
    const ids = sorted.map((s) => s.id);
    const i = ids.indexOf(stepId);
    if (i < 0) return;
    const j = i + direction;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try {
      currentFlow = await api.reorderSteps(currentFlow.slug, ids);
      setDirty(false);
      renderSteps();
      renderFlowList();
    } catch (err) {
      setBanner(err.message, "error");
    }
  }

  async function openFlow(slug) {
    if (dirty && !confirm("Du har ugemte ændringer. Fortsæt uden at gemme?")) return;
    try {
      currentFlow = await api.getFlow(slug);
      isNewFlow = false;
      fillFlowForm(currentFlow);
      renderSteps();
      renderFlowList();
      showPanel("editor");
      setDirty(false);
      setBanner("");
    } catch (err) {
      setBanner(err.message, "error");
    }
  }

  function startNewFlow() {
    if (dirty && !confirm("Du har ugemte ændringer. Fortsæt?")) return;
    isNewFlow = true;
    currentFlow = {
      slug: "",
      name: "",
      description: "",
      is_default: false,
      is_active: true,
      steps: [],
    };
    fillFlowForm(currentFlow);
    renderSteps();
    renderFlowList();
    showPanel("editor");
    setDirty(true);
    setBanner("");
  }

  async function saveFlow() {
    const payload = {
      name: $("flow-name").value.trim(),
      description: $("flow-description").value.trim(),
      is_default: $("flow-default").checked,
      is_active: $("flow-active").checked,
    };
    if (!payload.name) {
      setBanner("Navn er påkrævet.", "error");
      return;
    }
    try {
      if (isNewFlow) {
        payload.slug = $("flow-slug").value.trim().toLowerCase();
        if (!payload.slug) {
          setBanner("Slug er påkrævet.", "error");
          return;
        }
        currentFlow = await api.createFlow(payload);
        isNewFlow = false;
        await loadFlows();
        fillFlowForm(currentFlow);
        setBanner("Flow oprettet.", "ok");
      } else {
        currentFlow = await api.updateFlow(currentFlow.slug, payload);
        await loadFlows();
        fillFlowForm(currentFlow);
        setBanner("Flow gemt.", "ok");
      }
      setDirty(false);
      renderFlowList();
      renderSteps();
    } catch (err) {
      setBanner(err.message, "error");
    }
  }

  async function deleteCurrentFlow() {
    if (!currentFlow || isNewFlow) return;
    if (
      !confirm(
        "Slet eller deaktiver denne flow? Hvis medarbejdere er tildelt, deaktiveres den kun (is_active=false)."
      )
    ) {
      return;
    }
    try {
      const result = await api.deleteFlow(currentFlow.slug);
      await loadFlows();
      currentFlow = null;
      isNewFlow = false;
      showPanel("empty");
      setDirty(false);
      setBanner(
        result.deactivated
          ? "Flow deaktiveret (har tildelinger)."
          : "Flow slettet.",
        "ok"
      );
      renderFlowList();
    } catch (err) {
      setBanner(err.message, "error");
    }
  }

  function buildConfigFromForm(typeId) {
    const type = componentTypes.find((t) => t.type_id === typeId);
    if (!type) return {};
    if (typeId === "info_link") {
      return {
        body: $("cfg-body") ? $("cfg-body").value : "",
        url: $("cfg-url").value.trim(),
        requires_read: $("cfg-requires-read").checked,
      };
    }
    if (typeId === "checkbox") {
      return { label: $("cfg-label").value.trim() };
    }
    if (typeId === "form") {
      const fields = [];
      document.querySelectorAll(".form-field-row").forEach((row) => {
        const name = row.querySelector(".ff-name").value.trim();
        if (!name) return;
        fields.push({
          name,
          label: row.querySelector(".ff-label").value.trim(),
          type: row.querySelector(".ff-type").value,
          required: row.querySelector(".ff-req").checked,
        });
      });
      return { fields };
    }
    if (typeId === "calendar_meeting") {
      return {
        with_email: $("cfg-with-email").value.trim(),
        duration_minutes: parseInt($("cfg-duration").value, 10) || 30,
        suggested_window: $("cfg-window").value.trim(),
      };
    }
    return type.default_config || {};
  }

  function renderConfigFields(typeId, config) {
    const container = $("config-fields");
    container.innerHTML = "";
    const cfg = config || {};
    if (typeId === "info_link") {
      container.innerHTML =
        '<div class="field"><label>Brødtekst</label><textarea id="cfg-body" rows="2"></textarea></div>' +
        '<div class="field"><label>URL</label><input type="url" id="cfg-url" required></div>' +
        '<label class="check"><input type="checkbox" id="cfg-requires-read"> Kræver læst</label>';
      $("cfg-body").value = cfg.body || "";
      $("cfg-url").value = cfg.url || "https://";
      $("cfg-requires-read").checked = cfg.requires_read !== false;
    } else if (typeId === "checkbox") {
      container.innerHTML =
        '<div class="field"><label>Label</label><input type="text" id="cfg-label" required></div>';
      $("cfg-label").value = cfg.label || "Done?";
    } else if (typeId === "form") {
      const wrap = document.createElement("div");
      wrap.innerHTML = "<label>Felter</label>";
      const list = document.createElement("div");
      list.id = "form-fields-list";
      wrap.appendChild(list);
      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "btn ghost";
      addBtn.textContent = "+ Felt";
      addBtn.addEventListener("click", () => appendFormFieldRow(list, {}));
      wrap.appendChild(addBtn);
      container.appendChild(wrap);
      (cfg.fields || [{ name: "example", label: "Example", type: "text", required: true }]).forEach(
        (f) => appendFormFieldRow(list, f)
      );
    } else if (typeId === "calendar_meeting") {
      container.innerHTML =
        '<div class="field"><label>Med (email)</label><input type="email" id="cfg-with-email" required></div>' +
        '<div class="field"><label>Varighed (min)</label><input type="number" id="cfg-duration" min="5" max="240" value="30"></div>' +
        '<div class="field"><label>Forslaget vindue</label><input type="text" id="cfg-window" placeholder="fx first week"></div>';
      $("cfg-with-email").value = cfg.with_email || "";
      $("cfg-duration").value = cfg.duration_minutes || 30;
      $("cfg-window").value = cfg.suggested_window || "";
    }
    syncConfigJson();
  }

  function appendFormFieldRow(list, field) {
    const row = document.createElement("div");
    row.className = "form-field-row";
    row.innerHTML =
      '<input class="ff-name" placeholder="name" pattern="[a-zA-Z][a-zA-Z0-9_]*">' +
      '<input class="ff-label" placeholder="Label">' +
      '<select class="ff-type"><option value="text">text</option><option value="longtext">longtext</option>' +
      '<option value="email">email</option><option value="number">number</option>' +
      '<option value="date">date</option><option value="boolean">boolean</option></select>' +
      '<label class="check"><input type="checkbox" class="ff-req" checked> Req</label>' +
      '<button type="button" class="btn ghost danger">×</button>';
    row.querySelector(".ff-name").value = field.name || "";
    row.querySelector(".ff-label").value = field.label || "";
    row.querySelector(".ff-type").value = field.type || "text";
    row.querySelector(".ff-req").checked = field.required !== false;
    row.querySelector("button").addEventListener("click", () => {
      row.remove();
      syncConfigJson();
    });
    row.querySelectorAll("input,select").forEach((el) => {
      el.addEventListener("change", syncConfigJson);
      el.addEventListener("input", syncConfigJson);
    });
    list.appendChild(row);
  }

  function syncConfigJson() {
    const typeId = $("step-type").value;
    try {
      const cfg = buildConfigFromForm(typeId);
      $("step-config-json").value = JSON.stringify(cfg, null, 2);
      $("config-json-error").textContent = "";
    } catch (e) {
      $("config-json-error").textContent = e.message;
    }
  }

  function parseConfigJson() {
    const raw = $("step-config-json").value.trim();
    if (!raw) return {};
    return JSON.parse(raw);
  }

  function openStepDialog(step) {
    editingStepId = step ? step.id : null;
    $("step-dialog-title").textContent = step ? "Rediger trin" : "Nyt trin";
    const typeSelect = $("step-type");
    typeSelect.innerHTML = "";
    componentTypes.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.type_id;
      opt.textContent = t.label;
      typeSelect.appendChild(opt);
    });
    if (step) {
      $("step-order").value = step.order;
      $("step-type").value = step.component_type;
      $("step-title").value = step.title;
      $("step-description").value = step.description || "";
      $("step-required").checked = step.is_required;
      renderConfigFields(step.component_type, step.config);
    } else {
      const nextOrder =
        currentFlow && currentFlow.steps.length
          ? Math.max(...currentFlow.steps.map((s) => s.order)) + 1
          : 1;
      $("step-order").value = nextOrder;
      const def = componentTypes[0];
      $("step-type").value = def ? def.type_id : "info_link";
      $("step-title").value = "";
      $("step-description").value = "";
      $("step-required").checked = true;
      renderConfigFields(
        $("step-type").value,
        def ? def.default_config : {}
      );
    }
    $("step-dialog").showModal();
  }

  async function saveStepFromDialog(e) {
    e.preventDefault();
    if (!currentFlow || isNewFlow) {
      setBanner("Gem flow først, før du tilføjer trin.", "error");
      return;
    }
    let config;
    try {
      if ($("step-config-json").value.trim()) {
        config = parseConfigJson();
      } else {
        config = buildConfigFromForm($("step-type").value);
      }
    } catch (err) {
      $("config-json-error").textContent = "Ugyldig JSON: " + err.message;
      return;
    }
    const payload = {
      order: parseInt($("step-order").value, 10),
      component_type: $("step-type").value,
      title: $("step-title").value.trim(),
      description: $("step-description").value.trim(),
      is_required: $("step-required").checked,
      config,
    };
    try {
      if (editingStepId) {
        currentFlow = await api.updateStep(currentFlow.slug, editingStepId, payload);
      } else {
        currentFlow = await api.createStep(currentFlow.slug, payload);
      }
      $("step-dialog").close();
      await loadFlows();
      renderSteps();
      renderFlowList();
      setBanner("Trin gemt.", "ok");
    } catch (err) {
      setBanner(err.message, "error");
    }
  }

  async function removeStep(stepId) {
    if (!currentFlow || !confirm("Slet dette trin?")) return;
    try {
      currentFlow = await api.deleteStep(currentFlow.slug, stepId);
      await loadFlows();
      renderSteps();
      setBanner("Trin slettet.", "ok");
    } catch (err) {
      setBanner(err.message, "error");
    }
  }

  async function loadFlows() {
    const data = await api.listFlows();
    flows = data.results || [];
  }

  async function init() {
    try {
      const ct = await api.listComponentTypes();
      componentTypes = ct.results || [];
      const sel = $("step-type");
      componentTypes.forEach((t) => {
        const opt = document.createElement("option");
        opt.value = t.type_id;
        opt.textContent = t.label;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", () => {
        const t = componentTypes.find((x) => x.type_id === sel.value);
        renderConfigFields(sel.value, t ? t.default_config : {});
      });

      await loadFlows();
      renderFlowList();
      showPanel("empty");
    } catch (err) {
      setBanner(err.message || "Kunne ikke indlæse data.", "error");
    }
  }

  $("btn-new-flow").addEventListener("click", startNewFlow);
  $("btn-back-list").addEventListener("click", () => {
    if (dirty && !confirm("Ugemedte ændringer — forlad editor?")) return;
    currentFlow = null;
    showPanel("empty");
    renderFlowList();
    setDirty(false);
  });
  $("btn-save-flow").addEventListener("click", saveFlow);
  $("btn-delete-flow").addEventListener("click", deleteCurrentFlow);
  $("btn-add-step").addEventListener("click", () => {
    if (isNewFlow) {
      setBanner("Gem flow først.", "error");
      return;
    }
    openStepDialog(null);
  });
  $("btn-step-cancel").addEventListener("click", () => $("step-dialog").close());
  $("step-form").addEventListener("submit", saveStepFromDialog);
  $("step-config-json").addEventListener("blur", () => {
    try {
      parseConfigJson();
      $("config-json-error").textContent = "";
    } catch (e) {
      $("config-json-error").textContent = "Ugyldig JSON";
    }
  });

  ["flow-name", "flow-description", "flow-default", "flow-active", "flow-slug"].forEach(
    (id) => {
      const el = $(id);
      if (el) {
        el.addEventListener("input", () => setDirty(true));
        el.addEventListener("change", () => setDirty(true));
      }
    }
  );

  init();
})();
