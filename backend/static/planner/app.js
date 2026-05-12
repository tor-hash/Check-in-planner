/* eslint-disable no-console */
/**
 * planner/app.js — bootstrap entry point.
 *
 * Phase 5: until the legacy code in checkin-planner.html is fully extracted
 * into modules, this file just verifies that api-bridge.js loaded and exposes
 * a simple namespace for the new modules to attach to.
 *
 * Once Phase 5 completes, this becomes the SPA bootstrap (mounts views,
 * wires routing, hydrates the store).
 */
(function () {
  "use strict";

  if (!window.PlannerApi) {
    console.error("[planner] PlannerApi not loaded — api-bridge.js missing?");
    return;
  }

  window.Planner = window.Planner || {};
  window.Planner.modules = window.Planner.modules || {};

  // Allow modules to register themselves so the bootstrap can iterate later.
  window.Planner.register = function register(name, factory) {
    if (window.Planner.modules[name]) {
      console.warn("[planner] module '" + name + "' already registered");
      return;
    }
    try {
      window.Planner.modules[name] = factory(window.PlannerApi);
    } catch (err) {
      console.error("[planner] module '" + name + "' failed to load", err);
    }
  };

  console.info("[planner] bootstrap ready, " + Object.keys(window.Planner.modules).length + " modules registered");
})();
