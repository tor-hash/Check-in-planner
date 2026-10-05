/* global OnboardingManageApi */
// "Indstillinger" tab: the system account (owns meetings, sends the welcome
// email, uploads to Drive) and the Google Drive Employee folder used for
// employee documents, with a status checklist. See apps/onboarding/drive.py.
(function () {
  "use strict";

  const api = window.OnboardingManageApi;
  const $ = (id) => document.getElementById(id);
  let loaded = false;

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

  function line(id, ok, html) {
    const el = $(id);
    el.className = ok ? "ok" : "todo";
    el.innerHTML = (ok ? "✓ " : "• ") + html;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function render(cfg) {
    $("set-system-email").value = cfg.scheduler_email || "";
    $("set-system-email-hint").textContent =
      cfg.system_email_source === "default"
        ? "Standardværdien fra opsætningen bruges. Gem en anden adresse for at skifte."
        : cfg.system_email_source === "none"
          ? "Ingen systemkonto: møder oprettes i første deltagers kalender, velkomstmailen sendes fra den der tildeler flowet, og upload til Drive er slået fra."
          : "Lad feltet stå tomt og gem for at slå systemkontoen fra.";
    const who = escapeHtml(cfg.scheduler_email || "systemkontoen");
    if (!cfg.scheduler_email) {
      line("set-scheduler-signin", false, "Ingen systemkonto valgt — vælg en ovenfor for at bruge Drive.");
    } else {
      line(
        "set-scheduler-signin",
        cfg.scheduler_signed_in,
        cfg.scheduler_signed_in
          ? who + " er logget ind og forbundet til Google."
          : who + " skal logge ind i planner'en én gang."
      );
    }
    line(
      "set-scheduler-drive",
      cfg.scheduler_drive_connected,
      cfg.scheduler_drive_connected
        ? who + " har givet adgang til Google Drive."
        : who + ' har ikke givet Drive-adgang endnu. Log ind som ' + who +
            ' og klik <a href="/onboarding/drive/connect/">Giv Drive-adgang</a>.'
    );
    line(
      "set-folder-status",
      !!cfg.drive_root_folder_id,
      cfg.drive_root_folder_id
        ? 'Employee-mappe: <a href="' + escapeHtml(cfg.drive_root_folder_url) +
            '" target="_blank" rel="noopener">' + escapeHtml(cfg.drive_root_folder_name || cfg.drive_root_folder_id) +
            "</a>" + (cfg.updated_by ? " (sat af " + escapeHtml(cfg.updated_by) + ")" : "")
        : "Ingen Employee-mappe valgt endnu — indsæt linket nedenfor."
    );
    $("set-drive-folder").value = cfg.drive_root_folder_url || "";
  }

  async function load() {
    try {
      render(await api.getSettings());
    } catch (err) {
      loaded = false;
      setBanner(err.message || "Kunne ikke indlæse indstillinger.", "error");
    }
  }

  async function saveSystemEmail() {
    const email = $("set-system-email").value.trim();
    if (
      !email &&
      !confirm("Slå systemkontoen fra? Møder oprettes så i deltagernes egne kalendere og Drive-upload slås fra.")
    ) {
      return;
    }
    try {
      const cfg = await api.saveSettings({ system_email: email });
      render(cfg);
      setBanner(email ? "Systemkonto gemt: " + email : "Systemkonto slået fra.", "ok");
    } catch (err) {
      setBanner(err.message || "Kunne ikke gemme.", "error");
    }
  }

  async function save() {
    try {
      const cfg = await api.saveSettings({ drive_root_folder: $("set-drive-folder").value.trim() });
      render(cfg);
      setBanner(cfg.drive_root_folder_id ? "Employee-mappe gemt." : "Employee-mappe fjernet.", "ok");
    } catch (err) {
      setBanner(err.message || "Kunne ikke gemme.", "error");
    }
  }

  $("btn-save-settings").addEventListener("click", save);
  $("btn-save-system-email").addEventListener("click", saveSystemEmail);

  window.OnboardingSettingsEditor = {
    ensureReady() {
      if (loaded) return;
      loaded = true;
      load();
    },
    reload: load,
  };
})();
