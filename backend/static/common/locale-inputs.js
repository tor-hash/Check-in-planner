/*
 * Danish date/time fields everywhere: dd/mm/åååå and 24-hour tt:mm.
 *
 * Browsers draw <input type="date|time|datetime-local"> in the *browser's*
 * locale (mm/dd/yyyy and AM/PM on an English Windows/Chrome) and ignore the
 * page's lang. This script swaps every such input for text field(s) in Danish
 * format, while keeping the original input in the DOM as the source of truth:
 *
 *   - existing code keeps reading/writing `input.value` in ISO
 *     (yyyy-mm-dd / hh:mm / yyyy-mm-ddThh:mm) exactly as before;
 *   - setting `.value` or `.disabled` from code updates the visible fields;
 *   - typing a valid value fires the usual `input` + `change` events on the
 *     original, so existing listeners keep working;
 *   - the 📅 button opens the browser's own calendar picker.
 *
 * Applies to inputs present at load and any added later (MutationObserver).
 * Opt out per input with data-native-date.
 * Also exposes window.BCTDate.format("2026-11-02") -> "02/11/2026".
 */
(function () {
  "use strict";

  const PROTO = HTMLInputElement.prototype;
  const VALUE = Object.getOwnPropertyDescriptor(PROTO, "value");
  const DISABLED = Object.getOwnPropertyDescriptor(PROTO, "disabled");
  const REQUIRED = Object.getOwnPropertyDescriptor(PROTO, "required");
  const pad = (n) => String(n).padStart(2, "0");

  function isoToDa(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? m[3] + "/" + m[2] + "/" + m[1] : "";
  }

  function daToIso(text) {
    const m = /^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})\s*$/.exec(text || "");
    if (!m) return null;
    let y = parseInt(m[3], 10);
    if (m[3].length === 2) y += 2000;
    const mo = parseInt(m[2], 10);
    const d = parseInt(m[1], 10);
    const dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
    return y + "-" + pad(mo) + "-" + pad(d);
  }

  function normTime(text) {
    const m = /^\s*(\d{1,2})(?:[:.]?(\d{2}))?\s*$/.exec(text || "");
    if (!m) return null;
    const h = parseInt(m[1], 10);
    const mi = m[2] ? parseInt(m[2], 10) : 0;
    if (h > 23 || mi > 59) return null;
    return pad(h) + ":" + pad(mi);
  }

  function injectStyle() {
    if (document.getElementById("bct-locale-inputs-style")) return;
    const style = document.createElement("style");
    style.id = "bct-locale-inputs-style";
    style.textContent =
      ".bct-dt{display:inline-flex;align-items:center;gap:6px;position:relative;max-width:100%}" +
      ".bct-dt-block{display:flex;width:100%}" +
      ".bct-dt input.bct-dt-text{flex:1 1 auto;min-width:0}" +
      ".bct-dt input.bct-dt-date{min-width:7.5em}" +
      ".bct-dt input.bct-dt-time{width:5.5em;flex:0 0 auto}" +
      ".bct-dt input.bct-dt-invalid{border-color:#e06c6c !important;outline-color:#e06c6c}" +
      ".bct-dt-native{position:absolute !important;left:0;bottom:0;width:1px !important;height:1px !important;" +
      "opacity:0 !important;pointer-events:none !important;padding:0 !important;border:0 !important;margin:0 !important}" +
      ".bct-dt-pick{background:none;border:1px solid transparent;border-radius:6px;cursor:pointer;" +
      "padding:2px 4px;font-size:15px;line-height:1;color:inherit;flex:0 0 auto}" +
      ".bct-dt-pick:hover{border-color:currentColor}" +
      ".bct-dt-pick:disabled{opacity:.4;cursor:default}";
    document.head.appendChild(style);
  }

  function makeText(original, kind) {
    const t = document.createElement("input");
    t.type = "text";
    t.className = (original.className ? original.className + " " : "") + "bct-dt-text bct-dt-" + kind;
    t.inputMode = "numeric";
    t.autocomplete = "off";
    t.placeholder = kind === "date" ? "dd/mm/åååå" : "tt:mm";
    t.maxLength = kind === "date" ? 10 : 5;
    t.title = kind === "date" ? "Dato (dd/mm/åååå)" : "Tidspunkt (24-timer, tt:mm)";
    const style = original.getAttribute("style");
    if (style) t.setAttribute("style", style);
    return t;
  }

  function enhance(original) {
    if (original.dataset.bctDt || original.hasAttribute("data-native-date")) return;
    const kind = original.type; // date | time | datetime-local
    if (kind !== "date" && kind !== "time" && kind !== "datetime-local") return;
    original.dataset.bctDt = "1";
    injectStyle();

    const wrap = document.createElement("span");
    // Full-width when the original was (e.g. `.field input { width: 100% }`);
    // inline for small inputs like a table cell or "Arbejdstid 09:00 – 17:00".
    const cs = getComputedStyle(original);
    const parentWidth = original.parentNode.clientWidth || 0;
    // (Not computed display: flex/grid children always report "block".)
    const block =
      kind !== "time" &&
      (cs.width.endsWith("%") ||
        (original.offsetWidth > 0 && parentWidth > 0 && original.offsetWidth >= parentWidth - 40));
    wrap.className = "bct-dt" + (block ? " bct-dt-block" : "");
    original.parentNode.insertBefore(wrap, original);

    const dateText = kind === "time" ? null : makeText(original, "date");
    const timeText = kind === "date" ? null : makeText(original, "time");
    if (dateText) wrap.appendChild(dateText);
    if (timeText) wrap.appendChild(timeText);

    let pick = null;
    if (kind !== "time") {
      pick = document.createElement("button");
      pick.type = "button";
      pick.className = "bct-dt-pick";
      pick.textContent = "📅";
      pick.title = "Vælg i kalender";
      pick.addEventListener("click", () => {
        try {
          original.showPicker();
        } catch (_) {
          original.focus();
        }
      });
      wrap.appendChild(pick);
    }

    wrap.appendChild(original);
    original.classList.add("bct-dt-native");
    original.tabIndex = -1;
    original.setAttribute("aria-hidden", "true");

    // A <label for="id"> should focus the visible field.
    if (original.id) {
      document.querySelectorAll('label[for="' + CSS.escape(original.id) + '"]').forEach((l) => {
        l.addEventListener("click", (e) => {
          e.preventDefault();
          (dateText || timeText).focus();
        });
      });
    }

    function render() {
      const v = VALUE.get.call(original) || "";
      if (dateText) dateText.value = isoToDa(v);
      if (timeText) {
        const tm = kind === "time" ? v : (v.split("T")[1] || "");
        timeText.value = tm.slice(0, 5);
      }
      [dateText, timeText].forEach((el) => {
        if (!el) return;
        el.classList.remove("bct-dt-invalid");
        el.setCustomValidity("");
      });
    }

    function setDisabled(flag) {
      [dateText, timeText, pick].forEach((el) => el && (el.disabled = !!flag));
    }

    function setRequired(flag) {
      [dateText, timeText].forEach((el) => el && (el.required = !!flag));
    }

    // Programmatic value/disabled/required changes keep the visible fields in sync.
    Object.defineProperty(original, "value", {
      configurable: true,
      get() {
        return VALUE.get.call(original);
      },
      set(v) {
        VALUE.set.call(original, v);
        render();
      },
    });
    Object.defineProperty(original, "disabled", {
      configurable: true,
      get() {
        return DISABLED.get.call(original);
      },
      set(v) {
        DISABLED.set.call(original, v);
        setDisabled(v);
      },
    });
    Object.defineProperty(original, "required", {
      configurable: true,
      get() {
        return REQUIRED.get.call(original);
      },
      set(v) {
        REQUIRED.set.call(original, v);
        setRequired(v);
      },
    });
    // Validation happens on the visible field; the hidden one must never block a form.
    const wasRequired = REQUIRED.get.call(original);
    REQUIRED.set.call(original, false);
    setRequired(wasRequired);
    setDisabled(DISABLED.get.call(original));

    function commit(fireInputOnly) {
      let next;
      let ok = true;
      if (kind === "date") {
        const raw = dateText.value.trim();
        next = raw ? daToIso(raw) : "";
        ok = next !== null;
      } else if (kind === "time") {
        const raw = timeText.value.trim();
        next = raw ? normTime(raw) : "";
        ok = next !== null;
      } else {
        const rawD = dateText.value.trim();
        const rawT = timeText.value.trim();
        if (!rawD && !rawT) next = "";
        else {
          const d = daToIso(rawD);
          const t = rawT ? normTime(rawT) : "00:00";
          ok = !!d && !!t;
          next = ok ? d + "T" + t : null;
        }
      }
      [dateText, timeText].forEach((el) => {
        if (!el) return;
        el.classList.toggle("bct-dt-invalid", !ok);
        el.setCustomValidity(ok ? "" : kind === "time" ? "Skriv tidspunktet som tt:mm" : "Skriv datoen som dd/mm/åååå");
      });
      if (!ok) return;
      if (next === (VALUE.get.call(original) || "")) return;
      VALUE.set.call(original, next);
      original.dispatchEvent(new Event("input", { bubbles: true }));
      if (!fireInputOnly) original.dispatchEvent(new Event("change", { bubbles: true }));
    }

    [dateText, timeText].forEach((el) => {
      if (!el) return;
      // While typing: only commit complete values, and only fire "input".
      el.addEventListener("input", () => {
        const full = el === dateText ? el.value.trim().length >= 8 : el.value.trim().length >= 4;
        if (full || el.value.trim() === "") commit(true);
      });
      el.addEventListener("change", () => {
        commit(false);
        render2IfValid();
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") commit(false);
      });
    });

    // After a committed edit, tidy the text (e.g. "2/3/26" -> "02/03/2026").
    function render2IfValid() {
      const invalid = [dateText, timeText].some((el) => el && el.classList.contains("bct-dt-invalid"));
      if (!invalid) render();
    }

    // The native picker (📅) changes the original directly.
    original.addEventListener("input", (e) => {
      if (e.isTrusted) render();
    });
    original.addEventListener("change", (e) => {
      if (e.isTrusted) render();
    });

    render();
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.matches && root.matches('input[type="date"],input[type="time"],input[type="datetime-local"]')) {
      enhance(root);
    }
    root
      .querySelectorAll('input[type="date"],input[type="time"],input[type="datetime-local"]')
      .forEach(enhance);
  }

  function start() {
    scan(document.body);
    new MutationObserver((mutations) => {
      mutations.forEach((m) => m.addedNodes.forEach((n) => n.nodeType === 1 && scan(n)));
    }).observe(document.body, { childList: true, subtree: true });
  }

  window.BCTDate = {
    /** "2026-11-02" (or an ISO datetime) -> "02/11/2026". */
    format(iso) {
      return isoToDa(iso) || iso || "";
    },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
