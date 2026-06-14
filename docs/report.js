/*
 * report.js — "Report an Issue" pop-up. Posts a bug report (free text + optional
 * email + optional screenshot) to the backend, which stores it and emails the dev.
 * Works signed in or out. No account required.
 */
(function () {
  "use strict";

  const API_BASE =
    location.hostname === "127.0.0.1" || location.hostname === "localhost"
      ? "http://127.0.0.1:8090"
      : "https://monsterbox-api.onrender.com";

  // engine.js intercepts any path containing "/api/" for its local shim, so use
  // the saved real fetch to actually reach the backend.
  const directFetch = window.sfDirectFetch || window.fetch.bind(window);
  const $ = (id) => document.getElementById(id);

  function status(text, kind) {
    const s = $("reportStatus");
    if (s) { s.textContent = text || ""; s.className = "report-status" + (kind ? " " + kind : ""); }
  }

  function open() {
    $("reportMsg").value = "";
    $("reportShot").value = "";
    const sess = window.cloudGetSession && window.cloudGetSession();
    $("reportEmail").value = (sess && sess.user && sess.user.email) || "";
    status("");
    $("reportSend").disabled = false;
    $("reportModal").style.display = "flex";
    setTimeout(() => $("reportMsg").focus(), 30);
  }

  function close() {
    const m = $("reportModal");
    if (m) m.style.display = "none";
  }

  async function send() {
    const message = ($("reportMsg").value || "").trim();
    if (!message) { status("Please describe the issue first.", "err"); return; }

    const fd = new FormData();
    fd.append("message", message);
    const email = ($("reportEmail").value || "").trim();
    if (email) fd.append("email", email);
    const file = $("reportShot").files[0];
    if (file) {
      if (file.size > 6 * 1024 * 1024) { status("Screenshot is too large (max 6 MB).", "err"); return; }
      fd.append("screenshot", file);
    }

    $("reportSend").disabled = true;
    status("Sending…");
    try {
      const r = await directFetch(API_BASE + "/api/report", { method: "POST", body: fd });
      if (!r.ok) throw new Error("HTTP " + r.status);
      status("Thanks! Your report was sent.", "ok");
      setTimeout(close, 1400);
    } catch (e) {
      status("Couldn't send right now — please try again in a moment.", "err");
      $("reportSend").disabled = false;
    }
  }

  window.reportOpen = open;
  window.reportClose = close;
  window.reportSend = send;
})();
