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
      const participants = [];
      document.querySelectorAll(".cfg-participant-role").forEach((cb) => {
        if (cb.checked) participants.push(cb.value);
      });
      $("cfg-participant-emails")
        .value.split(/[\s,;]+/)
        .map((e) => e.trim())
        .filter(Boolean)
        .forEach((e) => {
          if (!participants.some((p) => p.toLowerCase() === e.toLowerCase())) participants.push(e);
        });
      if (participants.length === 0) throw new Error("Vælg mindst én deltager.");
      const dayOffsetRaw = $("cfg-day-offset").value.trim();
      const hour = $("cfg-time-hour").value;
      const minute = $("cfg-time-minute").value;
      const config = {
        participants,
        duration_minutes: parseInt($("cfg-duration").value, 10) || 30,
        day_offset: dayOffsetRaw === "" ? null : parseInt(dayOffsetRaw, 10),
        day_unit: $("cfg-day-unit").value,
        time_of_day: hour === "" ? "" : hour + ":" + (minute || "00"),
      };
      if (config.day_offset === null) {
        delete config.day_offset;
        delete config.day_unit;
      }
      if (!config.time_of_day) delete config.time_of_day;
      return config;
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
        '<div class="field"><label>Deltagere</label>' +
        '<label class="check"><input type="checkbox" class="cfg-participant-role" value="leder"> Medarbejderens leder</label>' +
        '<label class="check"><input type="checkbox" class="cfg-participant-role" value="buddy"> Medarbejderens buddy</label>' +
        '<label class="check"><input type="checkbox" class="cfg-participant-role" value="assigning_manager"> Den der tildeler flowet</label>' +
        '<input type="text" id="cfg-participant-emails" placeholder="Andre e-mails, adskilt med komma (fx it@blackcapitaltechnology.com)">' +
        '<p class="hint">Medarbejderen inviteres altid. Mødet bookes på et tidspunkt hvor alle valgte deltagere er ledige, ' +
        'og oprettes af systemkontoen (Indstillinger), som også inviterer alle.</p></div>' +
        '<div class="field"><label>Varighed (min)</label><input type="number" id="cfg-duration" min="5" max="240" value="30"></div>' +
        '<div class="field"><label>Dage efter startdato (valgfrit)</label>' +
        '<div class="inline-row">' +
        '<input type="number" id="cfg-day-offset" min="0" placeholder="fx 30">' +
        '<select id="cfg-day-unit">' +
        '<option value="calendar">kalenderdage</option>' +
        '<option value="business">arbejdsdage</option>' +
        "</select></div>" +
        '<p class="hint"><b>Kalenderdage:</b> almindelige dage fra startdatoen (startdagen er 0). 30 = 30 dage efter start. ' +
        'Falder dagen på en weekend eller helligdag, rykkes mødet til næste arbejdsdag.<br>' +
        '<b>Arbejdsdage:</b> kun hverdage tæller (weekender og helligdage springes over). "Uge 1" betyder ' +
        'medarbejderens første fem arbejdsdage: 0 = startdagen, 1 = næste arbejdsdag, 5 = første dag i uge 2. ' +
        'Starter medarbejderen en torsdag, bliver "uge 1 · onsdag" (2) til mandag og "uge 1 · torsdag" (3) til tirsdag.<br>' +
        'Lad feltet stå tomt for at booke på selve startdatoen (dag 0). Der bookes aldrig før startdatoen.</p></div>' +
        '<div class="field"><label>Klokkeslæt (valgfrit, 24-timer)</label>' +
        '<div class="inline-row">' +
        '<select id="cfg-time-hour"><option value="">--</option></select>' +
        '<span>:</span>' +
        '<select id="cfg-time-minute"></select>' +
        "</div>" +
        '<p class="hint">Forsøges først på den beregnede dag — er en af deltagerne optaget der, findes næste tid hvor alle er ledige.</p></div>';
      // Older steps have a single with_email instead of participants;
      // blank means the leder (see components.py participant_tokens()).
      const knownRoles = ["leder", "buddy", "assigning_manager"];
      const tokens =
        Array.isArray(cfg.participants) && cfg.participants.length
          ? cfg.participants
          : [cfg.with_email || "leder"];
      document.querySelectorAll(".cfg-participant-role").forEach((cb) => {
        cb.checked = tokens.includes(cb.value);
      });
      $("cfg-participant-emails").value = tokens.filter((t) => !knownRoles.includes(t)).join(", ");
      $("cfg-duration").value = cfg.duration_minutes || 30;
      const hasOffset = cfg.day_offset !== null && cfg.day_offset !== undefined;
      $("cfg-day-offset").value = hasOffset ? cfg.day_offset : "";
      // A saved offset without a unit predates day_unit and means working
      // days; a brand-new step defaults to calendar days.
      $("cfg-day-unit").value = cfg.day_unit || (hasOffset ? "business" : "calendar");
      fillTimeSelects(cfg.time_of_day || "");
    }
    syncConfigJson();
  }

  // 24-hour time picker built from two selects, so the browser's locale
  // (AM/PM on en-US Windows) never changes how the time is shown.
  function fillTimeSelects(value) {
    const hourSel = $("cfg-time-hour");
    const minuteSel = $("cfg-time-minute");
    const pad = (n) => String(n).padStart(2, "0");
    for (let h = 0; h < 24; h++) hourSel.add(new Option(pad(h), pad(h)));
    for (let m = 0; m < 60; m += 5) minuteSel.add(new Option(pad(m), pad(m)));
    const match = /^(\d{1,2}):(\d{2})$/.exec(value);
    if (match) {
      const hh = pad(parseInt(match[1], 10));
      const mm = match[2];
      // Keep an off-grid saved minute (e.g. 07) selectable.
      if (![...minuteSel.options].some((o) => o.value === mm)) minuteSel.add(new Option(mm, mm));
      hourSel.value = hh;
      minuteSel.value = mm;
    } else {
      hourSel.value = "";
      minuteSel.value = "00";
    }
    minuteSel.disabled = hourSel.value === "";
    hourSel.addEventListener("change", () => {
      minuteSel.disabled = hourSel.value === "";
    });
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
      $("step-title-no").value = step.title_no || "";
      $("step-description-no").value = step.description_no || "";
      $("step-no-details").open = !!(step.title_no || step.description_no);
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
      $("step-title-no").value = "";
      $("step-description-no").value = "";
      $("step-no-details").open = false;
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
      title_no: $("step-title-no").value.trim(),
      description_no: $("step-description-no").value.trim(),
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
  // Keep the JSON textarea in step with the form. Save reads that
  // textarea first, so without this an edit in a typed field (e.g. the
  // calendar "Dage efter startdato") was silently dropped.
  ["input", "change"].forEach((evt) =>
    $("config-fields").addEventListener(evt, syncConfigJson)
  );
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
