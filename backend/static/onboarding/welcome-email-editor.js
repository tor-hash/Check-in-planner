/* global OnboardingManageApi */
(function () {
  "use strict";

  const api = window.OnboardingManageApi;

  let flows = [];
  let currentFlowSlug = null;
  let loaded = false;
  let dirty = false;
  let previewTimer = null;

  const $ = (id) => document.getElementById(id);

  // Mirrors welcome_email.MERGE_TAGS on the backend — purely documentation,
  // kept here so the "Merge-tags" panel doesn't need a round trip.
  const MERGE_TAGS = [
    ["employee_name", "Medarbejderens fulde navn"],
    ["employee_first_name", "Medarbejderens fornavn"],
    ["employee_email", "Medarbejderens e-mail"],
    ["manager_name", "Navnet på den leder, der tildeler flowet"],
    ["manager_email", "E-mailen på den leder, der tildeler flowet"],
    ["buddy_name", "Buddyens navn (tom hvis ikke udfyldt — brug {% if buddy_name %})"],
    ["buddy_email", "Buddyens e-mail (tom hvis ikke udfyldt)"],
    ["flow_name", "Navnet på onboarding-flowet"],
    ["position", "Medarbejderens stilling"],
    ["department", "Medarbejderens afdeling"],
    ["start_date", "Medarbejderens startdato (kan være tom)"],
    ["todo_steps", "Liste af ikke-møde-trin — {% for s in todo_steps %}{{ s.title }}{% endfor %}"],
    ["meeting_steps", "Liste af calendar_meeting-trin — samme .title/.description, plus .duration_minutes"],
  ];

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

  function renderMergeTags() {
    const el = $("we-merge-tags");
    el.innerHTML = "";
    MERGE_TAGS.forEach(([tag, desc]) => {
      const row = document.createElement("div");
      row.className = "merge-tag-row";
      const code = document.createElement("code");
      code.textContent = "{{ " + tag + " }}";
      const span = document.createElement("span");
      span.className = "hint";
      span.textContent = " — " + desc;
      row.appendChild(code);
      row.appendChild(span);
      el.appendChild(row);
    });
  }

  function fillFlowSelect(selectedSlug) {
    const sel = $("we-flow-select");
    sel.innerHTML = "";
    flows.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.slug;
      opt.textContent = f.name + (f.is_active ? "" : " (inaktiv)");
      if (f.slug === selectedSlug) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  function sourceHintText(template) {
    if (template.source === "own") {
      return "Denne velkomstmail er tilpasset dette flow.";
    }
    if (template.source === "fallback") {
      return (
        "Ingen tilpasset velkomstmail for dette flow — viser standard-skabelonen " +
        "fra flowet “" + template.fallback_flow_slug + "”. Gem for at oprette " +
        "en tilpasset version for dette flow."
      );
    }
    return (
      "Ingen velkomstmail er konfigureret endnu, hverken for dette flow eller som " +
      "standard. Viser den indbyggede start-skabelon — gem for at gøre den til den " +
      "faktiske skabelon for dette flow."
    );
  }

  async function loadTemplateForFlow(slug) {
    try {
      const template = await api.getWelcomeEmailTemplate(slug);
      $("we-subject").value = template.subject;
      $("we-html").value = template.html_body;
      $("we-is-default").checked = !!template.is_default_fallback;
      $("we-source-hint").textContent = sourceHintText(template);
      $("btn-we-reset").disabled = !template.has_own_template;
      setDirty(false);
      schedulePreview();
    } catch (err) {
      setBanner(err.message || "Kunne ikke indlæse velkomstmail.", "error");
    }
  }

  function setDirty(v) {
    dirty = v;
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(runPreview, 350);
  }

  async function runPreview() {
    if (!currentFlowSlug) return;
    const statusEl = $("we-preview-status");
    const frame = $("we-preview-frame");
    statusEl.textContent = "(opdaterer …)";
    try {
      const result = await api.previewWelcomeEmail(currentFlowSlug, {
        subject: $("we-subject").value,
        html_body: $("we-html").value,
      });
      frame.srcdoc = result.html;
      statusEl.textContent = "";
    } catch (err) {
      statusEl.textContent = "kunne ikke forhåndsvise: " + (err.message || "ukendt fejl");
      frame.srcdoc = "";
    }
  }

  async function selectFlow(slug) {
    if (dirty && !confirm("Ugemedte ændringer til velkomstmailen — skift flow?")) {
      fillFlowSelect(currentFlowSlug);
      return;
    }
    currentFlowSlug = slug;
    fillFlowSelect(slug);
    await loadTemplateForFlow(slug);
  }

  async function saveTemplate() {
    if (!currentFlowSlug) return;
    const subject = $("we-subject").value.trim();
    const htmlBody = $("we-html").value;
    if (!subject) {
      setBanner("Emnelinje er påkrævet.", "error");
      return;
    }
    if (!htmlBody.trim()) {
      setBanner("HTML-indhold er påkrævet.", "error");
      return;
    }
    try {
      await api.saveWelcomeEmailTemplate(currentFlowSlug, {
        subject,
        html_body: htmlBody,
        is_default_fallback: $("we-is-default").checked,
      });
      setBanner("Velkomstmail gemt.", "ok");
      await loadTemplateForFlow(currentFlowSlug);
    } catch (err) {
      setBanner(err.message || "Kunne ikke gemme velkomstmail.", "error");
    }
  }

  async function resetTemplate() {
    if (!currentFlowSlug) return;
    if (!confirm("Nulstil velkomstmailen for dette flow til standard-skabelonen? Dette kan ikke fortrydes.")) {
      return;
    }
    try {
      await api.resetWelcomeEmailTemplate(currentFlowSlug);
      setBanner("Velkomstmail nulstillet.", "ok");
      await loadTemplateForFlow(currentFlowSlug);
    } catch (err) {
      setBanner(err.message || "Kunne ikke nulstille velkomstmail.", "error");
    }
  }

  async function ensureReady() {
    if (loaded) return;
    loaded = true;
    renderMergeTags();
    try {
      const data = await api.listFlows();
      flows = data.results || [];
      if (!flows.length) {
        setBanner("Opret en flow først, før du kan redigere en velkomstmail.", "error");
        return;
      }
      const defaultFlow = flows.find((f) => f.is_default) || flows[0];
      currentFlowSlug = defaultFlow.slug;
      fillFlowSelect(currentFlowSlug);
      await loadTemplateForFlow(currentFlowSlug);
    } catch (err) {
      loaded = false;
      setBanner(err.message || "Kunne ikke indlæse flows.", "error");
    }
  }

  $("we-flow-select").addEventListener("change", (e) => selectFlow(e.target.value));
  $("we-subject").addEventListener("input", () => {
    setDirty(true);
    schedulePreview();
  });
  $("we-html").addEventListener("input", () => {
    setDirty(true);
    schedulePreview();
  });
  $("btn-we-save").addEventListener("click", saveTemplate);
  $("btn-we-reset").addEventListener("click", resetTemplate);

  window.OnboardingWelcomeEmailEditor = {
    ensureReady,
    isDirty: () => dirty,
  };
})();
