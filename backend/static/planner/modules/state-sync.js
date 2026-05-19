/* eslint-disable no-console */
/**
 * modules/state-sync.js
 *
 * Loads planner state from Django and persists mutations through granular
 * REST endpoints (Option B — no full-state PUT on every edit).
 */
(function () {
  "use strict";

  if (!window.Planner || typeof window.Planner.register !== "function") {
    return;
  }

  window.Planner.register("stateSync", function (api) {
    const OAUTH_CACHE_KEY = "bct-checkin-planner-oauth-cache";

    function setSyncPill(kind, message) {
      const el = document.getElementById("master-sync-status");
      if (!el) return;
      el.style.display = message ? "" : "none";
      el.className = "sync-pill" + (kind ? " " + kind : "");
      el.textContent = message || "";
    }

    function runSync(label, fn) {
      setSyncPill("", "🟡 Gemmer…");
      return Promise.resolve()
        .then(fn)
        .then(() => {
          setSyncPill("ok", "🟢 Gemt");
        })
        .catch((err) => {
          console.error("[stateSync]", label, err);
          const msg = (err && err.message) || String(err);
          setSyncPill("err", "🔴 " + msg.slice(0, 80));
          throw err;
        });
    }

    /** UI shape: { personId: { sessionIdx: "2026-05-12T10:00" } } */
    function isNestedCustomDates(customDates) {
      if (!customDates || typeof customDates !== "object") return false;
      return Object.values(customDates).some(
        (v) => v && typeof v === "object" && !Array.isArray(v)
      );
    }

    /** API/DB shape: { "personId:sessionIdx": "2026-05-12T10:00" } */
    function encodeCustomDates(nested) {
      const flat = {};
      Object.entries(nested || {}).forEach(([personId, sessions]) => {
        if (!sessions || typeof sessions !== "object") return;
        Object.entries(sessions).forEach(([sessionIdx, value]) => {
          if (value == null || value === "") return;
          flat[personId + ":" + sessionIdx] = String(value).slice(0, 64);
        });
      });
      return flat;
    }

    function decodeCustomDates(flatOrNested) {
      if (!flatOrNested || typeof flatOrNested !== "object") return {};
      if (isNestedCustomDates(flatOrNested)) {
        return JSON.parse(JSON.stringify(flatOrNested));
      }
      const nested = {};
      Object.entries(flatOrNested).forEach(([key, value]) => {
        if (typeof value !== "string") return;
        const sep = key.indexOf(":");
        if (sep <= 0) return;
        const personId = key.slice(0, sep);
        const sessionIdx = key.slice(sep + 1);
        if (!nested[personId]) nested[personId] = {};
        nested[personId][sessionIdx] = value;
      });
      return nested;
    }

    function defaultFnTags() {
      return [
        { label: "ENG", displayName: "Engineering", color: "#6ea8fe" },
        { label: "BD", displayName: "Business Development", color: "#f5a97f" },
        { label: "MKT", displayName: "Marketing", color: "#a6da95" },
        { label: "MGMT", displayName: "Management", color: "#c6a0f6" },
      ];
    }

    function normalizePayload(payload) {
      const p = payload || {};
      return {
        people: Array.isArray(p.people) ? p.people : [],
        mgrs: Array.isArray(p.mgrs) ? p.mgrs : [],
        teams: p.teams || { "team-1": [], "team-2": [], "team-3": [], pool: [] },
        startDate: p.startDate || "",
        customDates: decodeCustomDates(p.customDates || {}),
        workHours: p.workHours || {
          start: "09:00",
          end: "17:00",
          excludeLunch: true,
          weekdaysOnly: true,
        },
        oauth: loadOauthCache() || {
          lastFetch: null,
          busy: {},
          autoRefresh: false,
          lastErrors: [],
        },
        viewedMgrFilter: p.viewedMgrFilter == null ? "all" : p.viewedMgrFilter,
        weekOffset: p.weekOffset == null ? 0 : p.weekOffset,
        weeksPerSession: p.weeksPerSession == null ? 2 : p.weeksPerSession,
        projects: Array.isArray(p.projects) ? p.projects : [],
        journal: p.journal || {},
        fnTags: Array.isArray(p.fnTags) && p.fnTags.length ? p.fnTags : defaultFnTags(),
        rotationSessions: Array.isArray(p.rotationSessions) ? p.rotationSessions : [],
        bookings: Array.isArray(p.bookings) ? p.bookings : [],
        _meta: p._meta || {},
      };
    }

    function loadOauthCache() {
      try {
        const raw = sessionStorage.getItem(OAUTH_CACHE_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch {
        return null;
      }
    }

    function saveOauthCache(oauth) {
      try {
        if (oauth) sessionStorage.setItem(OAUTH_CACHE_KEY, JSON.stringify(oauth));
      } catch (_) {
        /* ignore quota */
      }
    }

    function mergeRotationSessions(existing, incoming) {
      const byKey = {};
      (existing || []).concat(incoming || []).forEach((s) => {
        byKey[s.cycleStart + ":" + s.sessionIndex] = s;
      });
      return Object.values(byKey);
    }

    async function loadFromServer() {
      const payload = await api.getState();
      return normalizePayload(payload);
    }

    async function loadRotation(upcoming = 32, fromDate = null) {
      const response = await api.getRotation(upcoming, fromDate);
      return response.sessions || [];
    }

    async function loadBookings() {
      const response = await api.listBookings({});
      return response.bookings || [];
    }

    async function refreshFromServer() {
      const payload = await loadFromServer();
      try {
        payload.rotationSessions = await loadRotation(32);
      } catch (err) {
        console.warn("[stateSync] rotation load failed", err);
      }
      if (typeof window.applyPlannerStatePayload === "function") {
        window.applyPlannerStatePayload(payload);
      }
      return payload;
    }

    async function savePerson(person, { isNew = false } = {}) {
      if (isNew) {
        await api.createPerson(person);
      } else {
        await api.updatePerson(person.id, person);
      }
    }

    async function removePerson(personId) {
      await api.deletePerson(personId);
    }

    async function syncAllPeople(people) {
      const remote = (await api.listPeople()).people || [];
      const remoteIds = new Set(remote.map((p) => p.id));
      for (const person of people || []) {
        if (remoteIds.has(person.id)) {
          await api.updatePerson(person.id, person);
        } else {
          await api.createPerson(person);
        }
      }
    }

    async function saveTeam(team, personIds) {
      await api.replaceTeam(team, personIds || []);
    }

    async function syncAllTeams(teams) {
      const names = ["team-1", "team-2", "team-3", "pool"];
      for (const team of names) {
        await api.replaceTeam(team, (teams && teams[team]) || []);
      }
    }

    async function syncMgrs(mgrs) {
      const remote = (await api.listManagers()).mgrs || [];
      for (const id of mgrs || []) {
        if (!remote.includes(id)) {
          await api.createManager(id);
        }
      }
    }

    async function saveProject(project, { isNew = false, oldName = null } = {}) {
      if (isNew) {
        await api.createProject(project);
      } else {
        await api.updateProject(oldName || project.name, project);
      }
    }

    async function removeProject(name) {
      await api.deleteProject(name);
    }

    async function syncAllProjects(projects) {
      const remote = (await api.listProjects()).projects || [];
      for (const p of projects || []) {
        const exists = remote.some((r) => r.name === p.name);
        if (exists) {
          await api.updateProject(p.name, p);
        } else {
          await api.createProject(p);
        }
      }
    }

    async function syncFnTags(fnTags) {
      await api.replaceFunctionTags(fnTags || []);
    }

    async function syncCustomDates(customDates) {
      await api.updateCustomDates(encodeCustomDates(customDates));
    }

    async function syncConfig(partial) {
      await api.updateConfig(partial || {});
    }

    return {
      OAUTH_CACHE_KEY,
      setSyncPill,
      runSync,
      normalizePayload,
      encodeCustomDates,
      decodeCustomDates,
      loadOauthCache,
      saveOauthCache,
      loadFromServer,
      loadRotation,
      loadBookings,
      mergeRotationSessions,
      refreshFromServer,
      savePerson,
      removePerson,
      syncAllPeople,
      saveTeam,
      syncAllTeams,
      syncMgrs,
      saveProject,
      removeProject,
      syncAllProjects,
      syncFnTags,
      syncCustomDates,
      syncConfig,
    };
  });
})();
