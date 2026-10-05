/* global OnboardingManageApi */
// "Velkomstmail" tab: a library of welcome-email templates. Each template
// has a name and a language (da/no); one per language can be the default.
// Templates aren't tied to flows — the manager picks one in the
// "Tildel flow" dialog (employees-editor.js).
(function () {
  "use strict";

  const api = window.OnboardingManageApi;

  const LANGUAGE_LABELS = { da: "Dansk", no: "Norsk" };
  const COUNTRY_FOR_LANGUAGE = { da: "DK", no: "NO" };

  let templates = [];
  let starter = { subject: "", html_body: "" };
  let current = null; // template object being edited; {id: null, ...} for a new one
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
    ["manager_name", "Navnet på den, der tildeler flowet"],
    ["manager_email", "E-mailen på den, der tildeler flowet"],
    ["leder_name", "Navnet på medarbejderens leder"],
    ["leder_email", "E-mailen på medarbejderens leder"],
    ["buddy_name", "Buddyens navn (tom hvis ikke udfyldt — brug {% if buddy_name %})"],
    ["buddy_email", "Buddyens e-mail (tom hvis ikke udfyldt)"],
    ["flow_name", "Navnet på onboarding-flowet"],
    ["position", "Medarbejderens stilling"],
    ["department", "Medarbejderens afdeling"],
    ["start_date", "Medarbejderens startdato (kan være tom)"],
    ["todo_steps", "Ikke-møde-trin på medarbejderens sprog — {% for s in todo_steps %}{{ s.title }}{% endfor %}"],
    ["meeting_steps", "Møde-trin — samme .title/.description, plus .duration_minutes"],
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

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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

  function renderList() {
    const container = $("we-list");
    container.innerHTML = "";
    if (!templates.length) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent =
        "Ingen velkomstmails endnu. Indtil der findes en, sendes den indbyggede start-skabelon (dansk).";
      container.appendChild(p);
    }
    ["da", "no"].forEach((lang) => {
      templates
        .filter((t) => t.language === lang)
        .forEach((t) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "flow-card" + (current && current.id === t.id ? " active" : "");
          btn.innerHTML =
            '<span class="name">' + escapeHtml(t.name) + "</span>" +
            '<span class="meta">' +
            (t.is_default ? '<span class="badge">Standard</span>' : "") +
            escapeHtml(LANGUAGE_LABELS[t.language] || t.language) +
            "</span>";
          btn.addEventListener("click", () => openTemplate(t.id));
          container.appendChild(btn);
        });
    });
    ["da", "no"].forEach((lang) => {
      if (templates.length && !templates.some((t) => t.language === lang)) {
        const p = document.createElement("p");
        p.className = "hint";
        p.textContent =
          "Ingen " + LANGUAGE_LABELS[lang].toLowerCase() + " velkomstmail — " +
          (lang === "no"
            ? "medarbejdere i Norge får den indbyggede danske start-skabelon."
            : "medarbejdere i Danmark får den indbyggede start-skabelon.");
        container.appendChild(p);
      }
    });
  }

  function showEditor(show) {
    $("we-editor-panel").classList.toggle("hidden", !show);
    $("we-empty-state").classList.toggle("hidden", show);
  }

  function fillForm(t) {
    $("we-editor-title").textContent = t.id ? "Rediger velkomstmail" : "Ny velkomstmail";
    $("we-name").value = t.name || "";
    $("we-language").value = t.language || "da";
    $("we-subject").value = t.subject || "";
    $("we-html").value = t.html_body || "";
    $("we-is-default").checked = !!t.is_default;
    $("btn-we-delete").disabled = !t.id;
    $("btn-we-duplicate").disabled = !t.id;
    $("we-meta").textContent = t.updated_at
      ? "Sidst gemt " + new Date(t.updated_at).toLocaleString("da-DK") +
        (t.updated_by ? " af " + t.updated_by : "")
      : "";
    showEditor(true);
    dirty = !t.id;
    schedulePreview();
  }

  function confirmDiscard() {
    return !dirty || confirm("Ugemte ændringer til velkomstmailen — kassér dem?");
  }

  function openTemplate(id) {
    if (current && current.id === id) return;
    if (!confirmDiscard()) return;
    current = templates.find((t) => t.id === id) || null;
    if (current) fillForm(current);
    renderList();
  }

  function newTemplate(base) {
    if (!confirmDiscard()) return;
    const src = base || { subject: starter.subject, html_body: starter.html_body, language: "da" };
    current = {
      id: null,
      name: base ? base.name + " (kopi)" : "",
      language: src.language || "da",
      subject: src.subject,
      html_body: src.html_body,
      is_default: false,
    };
    fillForm(current);
    renderList();
    $("we-name").focus();
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(runPreview, 350);
  }

  async function runPreview() {
    if (!current) return;
    const statusEl = $("we-preview-status");
    const frame = $("we-preview-frame");
    const subject = $("we-subject").value;
    const htmlBody = $("we-html").value;
    if (!subject.trim() || !htmlBody.trim()) {
      statusEl.textContent = "(udfyld emne og HTML for at se forhåndsvisning)";
      frame.srcdoc = "";
      return;
    }
    statusEl.textContent = "(opdaterer …)";
    try {
      const result = await api.previewWelcomeEmail({
        subject,
        html_body: htmlBody,
        country: COUNTRY_FOR_LANGUAGE[$("we-language").value] || "DK",
      });
      frame.srcdoc = result.html;
      statusEl.textContent = "";
    } catch (err) {
      statusEl.textContent = "kunne ikke forhåndsvise: " + (err.message || "ukendt fejl");
      frame.srcdoc = "";
    }
  }

  async function reload(selectId) {
    const data = await api.listWelcomeEmails();
    templates = data.results || [];
    starter = data.starter || starter;
    current = selectId ? templates.find((t) => t.id === selectId) || null : null;
    renderList();
    if (current) {
      fillForm(current);
      dirty = false;
    } else {
      showEditor(false);
    }
  }

  async function saveTemplate() {
    if (!current) return;
    const payload = {
      name: $("we-name").value.trim(),
      language: $("we-language").value,
      subject: $("we-subject").value.trim(),
      html_body: $("we-html").value,
      is_default: $("we-is-default").checked,
    };
    if (!payload.name) return setBanner("Navn er påkrævet.", "error");
    if (!payload.subject) return setBanner("Emnelinje er påkrævet.", "error");
    if (!payload.html_body.trim()) return setBanner("HTML-indhold er påkrævet.", "error");
    try {
      const saved = current.id
        ? await api.updateWelcomeEmail(current.id, payload)
        : await api.createWelcomeEmail(payload);
      dirty = false;
      await reload(saved.id);
      setBanner("Velkomstmail gemt.", "ok");
    } catch (err) {
      setBanner(err.message || "Kunne ikke gemme velkomstmail.", "error");
    }
  }

  async function deleteTemplate() {
    if (!current || !current.id) return;
    if (
      !confirm(
        'Slet velkomstmailen "' + current.name + '"? Tildelinger der har valgt den, ' +
          "bruger i stedet standard-skabelonen for deres sprog."
      )
    ) {
      return;
    }
    try {
      await api.deleteWelcomeEmail(current.id);
      dirty = false;
      await reload(null);
      setBanner("Velkomstmail slettet.", "ok");
    } catch (err) {
      setBanner(err.message || "Kunne ikke slette velkomstmail.", "error");
    }
  }

  async function ensureReady() {
    if (loaded) return;
    loaded = true;
    renderMergeTags();
    try {
      await reload(null);
      const first = templates.find((t) => t.is_default) || templates[0];
      if (first) openTemplate(first.id);
    } catch (err) {
      loaded = false;
      setBanner(err.message || "Kunne ikke indlæse velkomstmails.", "error");
    }
  }

  ["we-name", "we-subject", "we-html"].forEach((id) =>
    $(id).addEventListener("input", () => {
      dirty = true;
      if (id !== "we-name") schedulePreview();
    })
  );
  ["we-language", "we-is-default"].forEach((id) =>
    $(id).addEventListener("change", () => {
      dirty = true;
      schedulePreview();
    })
  );
  $("btn-we-new").addEventListener("click", () => newTemplate(null));
  $("btn-we-duplicate").addEventListener("click", () => {
    if (current && current.id) {
      newTemplate({
        name: $("we-name").value.trim() || current.name,
        language: $("we-language").value,
        subject: $("we-subject").value,
        html_body: $("we-html").value,
      });
    }
  });
  $("btn-we-save").addEventListener("click", saveTemplate);
  $("btn-we-delete").addEventListener("click", deleteTemplate);

  window.OnboardingWelcomeEmailEditor = {
    ensureReady,
    isDirty: () => dirty,
  };
})();
