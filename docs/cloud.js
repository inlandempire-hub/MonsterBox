/*
 * cloud.js — optional account layer (Supabase email/password login).
 *
 * Local-first by design: signed OUT, MonsterBox behaves exactly as before
 * (everything in this browser's IndexedDB, no account needed). Signing IN is
 * optional and surfaces the user's MonsterBox access level; cloud SYNC of the
 * compendium is wired on top of this in the next step.
 *
 * Identity is handled entirely by Supabase. The user's plan/role (Pro, comp,
 * admin / "god account") lives in OUR backend and is read from /api/auth/me.
 */
(function () {
  "use strict";

  // --- public config (safe to ship; the anon key is meant to be public) ---
  const SUPABASE_URL = "https://rioxklylnljvozdbabgm.supabase.co";
  const SUPABASE_ANON_KEY =
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJpb3hrbHlsbmxqdm96ZGJhYmdtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODExODQ0MTcsImV4cCI6MjA5Njc2MDQxN30.WZmTwluvvGmvW1oZl3sy0CWMxy1Pj6xAcMbX-CLvFy0";

  // Where the MonsterBox backend lives. Local dev -> the FastAPI server on :8090.
  // (The production URL is filled in once the backend is deployed.)
  const API_BASE =
    location.hostname === "127.0.0.1" || location.hostname === "localhost"
      ? "http://127.0.0.1:8090"
      : "https://monsterbox-api.onrender.com";

  // bypass the IndexedDB fetch-shim so backend calls actually leave the browser
  const directFetch = window.sfDirectFetch || window.fetch.bind(window);
  const $ = (id) => document.getElementById(id);

  let supa = null;
  let session = null;   // Supabase session (null = signed out)
  let account = null;   // our backend's view: { email, plan, role, has_full_access }
  let curMsg = "authmsg";   // which view's message line msg() writes to

  function client() {
    if (supa) return supa;
    if (!window.supabase || !window.supabase.createClient) return null;
    supa = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    return supa;
  }

  // ---- backend account / entitlement ----
  let acctErr = null;   // why the last access check failed (for the diagnostic line)
  async function fetchAccount() {
    account = null; acctErr = null;
    if (!session) return;
    if (!API_BASE) { acctErr = "no server configured for this site"; return; }
    try {
      const r = await directFetch(API_BASE + "/api/auth/me", {
        headers: { Authorization: "Bearer " + session.access_token },
      });
      if (r.ok) { account = await r.json(); }
      else {
        acctErr = "server replied HTTP " + r.status;
        try { const t = (await r.text()) || ""; if (t) acctErr += " (" + t.slice(0, 80) + ")"; } catch (e) {}
      }
    } catch (e) {
      acctErr = "couldn't reach the server at " + API_BASE + " (is it running?)";
    }
    if (acctErr) console.warn("[MonsterBox] access check:", acctErr);
  }

  function accessTag() {
    if (!account || !account.has_full_access) return "Free";
    if (account.role === "admin") return "Admin";
    if (account.plan === "comp") return "Full access";
    return "Pro";
  }

  // ---- UI ----
  function displayName() {
    const m = (session && session.user && session.user.user_metadata) || {};
    const f = (m.first_name || "").trim(), l = (m.last_name || "").trim();
    if (f || l) return [f, l].filter(Boolean).join(" ");
    const email = (session && session.user && session.user.email) || "";
    return email.split("@")[0] || "Account";
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function render() {
    const btn = $("signinbtn");
    if (!btn) return;
    if (session) {
      const full = !!(account && account.has_full_access);
      btn.innerHTML = "Signed in: " + esc(displayName()) +
        ' <span class="signin-tag' + (full ? "" : " free") + '">' + esc(accessTag()) + "</span>";
      btn.classList.remove("primary"); btn.classList.add("signed");
      btn.title = ((session.user && session.user.email) || "") + " — " + accessTag();
    } else {
      btn.textContent = "Sign In";
      btn.classList.add("primary"); btn.classList.remove("signed");
      btn.title = "Sign in to sync your compendium across devices";
    }
  }

  function msg(text, kind) {
    const m = $(curMsg);
    if (m) { m.textContent = text || ""; m.className = "auth-msg" + (kind ? " " + kind : ""); }
  }

  // three views in one modal: sign-in / create-account / signed-in account.
  // The account view is a landscape card with its own header, so the shared
  // header is hidden and the box widens.
  function setView(view) {
    const account = view === "account";
    $("authForm").style.display = view === "signin" ? "block" : "none";
    $("authCreate").style.display = view === "create" ? "block" : "none";
    $("authAccount").style.display = account ? "flex" : "none";
    $("authHeader").style.display = account ? "none" : "block";
    $("authAcctActions").style.display = account ? "flex" : "none";
    $("authCloseShared").style.display = account ? "none" : "inline-block";
    $("authBox").classList.toggle("account-mode", account);
    if (!account) $("authTitle").textContent = view === "create" ? "Create account" : "Sign in";
    $("authModal").style.display = "flex";
  }
  function showSignIn() {
    curMsg = "authmsg"; msg("");
    setView("signin");
    const e = $("authEmail"); if (e) setTimeout(() => e.focus(), 30);
  }
  function showCreate() {
    curMsg = "authmsg2"; msg("");
    setView("create");
    const e = $("authNewEmail"); if (e) setTimeout(() => e.focus(), 30);
  }
  async function showModal() {
    if (!session) { showSignIn(); return; }
    setView("account");
    curMsg = "authmsg3"; msg("");
    $("authNameEdit").style.display = "none";
    $("authAcctName").textContent = displayName();
    $("authAcctEmail").textContent = (session.user && session.user.email) || "";
    paintTag();
    // re-check access in case the backend wasn't running when we first logged in
    await fetchAccount();
    paintTag();
    render();
  }
  function editName() {
    const meta = (session && session.user && session.user.user_metadata) || {};
    $("authEditFirst").value = meta.first_name || "";
    $("authEditLast").value = meta.last_name || "";
    curMsg = "authmsg3"; msg("");
    $("authNameEdit").style.display = "block";
  }
  function cancelEdit() { $("authNameEdit").style.display = "none"; curMsg = "authmsg3"; msg(""); }
  function paintTag() {
    const el = $("authAcctTag");
    if (!el) return;
    el.textContent = accessTag();
    el.classList.toggle("full", !!(account && account.has_full_access));
    const d = $("authAcctDiag");
    if (d) d.textContent = (!account && acctErr) ? ("Access not confirmed: " + acctErr) : "";
  }
  function closeModal() { const m = $("authModal"); if (m) m.style.display = "none"; }

  async function signIn() {
    const email = ($("authEmail").value || "").trim();
    const pw = $("authPass").value || "";
    if (!email || !pw) return msg("Enter your email and password.", "err");
    const c = client(); if (!c) return msg("Login is unavailable right now.", "err");
    msg("Signing in…");
    const { error } = await c.auth.signInWithPassword({ email, password: pw });
    if (error) return msg(error.message, "err");
    closeModal();
  }

  async function createAccount() {
    const first = ($("authFirst").value || "").trim();
    const last = ($("authLast").value || "").trim();
    const email = ($("authNewEmail").value || "").trim();
    const pw = $("authNewPass").value || "";
    const pw2 = $("authNewPass2").value || "";
    if (!first || !last) return msg("Enter your first and last name.", "err");
    if (!email || !pw || !pw2) return msg("Fill in email, password and confirm password.", "err");
    if (pw.length < 8) return msg("Password must be at least 8 characters.", "err");
    if (pw !== pw2) return msg("Passwords don't match.", "err");
    const c = client(); if (!c) return msg("Sign-up is unavailable right now.", "err");
    msg("Creating your account…");
    const { data, error } = await c.auth.signUp({
      email, password: pw,
      options: { data: { first_name: first, last_name: last } },
    });
    if (error) return msg(error.message, "err");
    // confirmation is on, so signUp returns no session — prompt to confirm by email
    if (data && data.session) closeModal();
    else msg("Account created. Check your email to confirm, then log in.", "ok");
  }

  async function saveName() {
    curMsg = "authmsg3";
    const first = ($("authEditFirst").value || "").trim();
    const last = ($("authEditLast").value || "").trim();
    if (!first || !last) return msg("Enter your first and last name.", "err");
    const c = client(); if (!c) return;
    msg("Saving…");
    const { data, error } = await c.auth.updateUser({ data: { first_name: first, last_name: last } });
    if (error) return msg(error.message, "err");
    if (data && data.user) session.user = data.user;   // refresh local copy
    $("authAcctName").textContent = displayName();
    $("authNameEdit").style.display = "none";          // collapse the editor
    render();
  }

  async function signOut() {
    const c = client();
    if (c) await c.auth.signOut();
    closeModal();
  }

  async function onAuth(newSession) {
    session = newSession || null;
    await fetchAccount();
    render();
    // let the rest of the app react (sync hooks attach here later)
    if (typeof window.onCloudAuthChange === "function") {
      try { window.onCloudAuthChange(session, account); } catch (e) {}
    }
  }

  function init() {
    // #signinbtn uses inline onclick="cloudOpen()"; Enter-to-submit is handled
    // by the <form> onsubmit.
    const c = client();
    if (!c) { render(); return; }   // supabase-js failed to load -> stay signed-out
    c.auth.getSession().then(({ data }) => onAuth(data ? data.session : null));
    c.auth.onAuthStateChange((_evt, s) => onAuth(s));
  }

  // sync.js reports its status here; show it on the account card
  window.onSyncStatus = function (s) {
    const el = $("authSyncStatus");
    if (!el) return;
    const text = { syncing: "Syncing your compendium…", synced: "Compendium synced to your account",
                   error: "Sync paused (couldn't reach the server)", off: "" };
    el.textContent = session ? (text[s] || "") : "";
    el.className = "acct-sync" + (s === "syncing" ? " syncing" : s === "error" ? " error" : "");
  };

  // expose for inline onclick handlers
  window.cloudOpen = showModal;
  window.cloudSignIn = signIn;
  window.cloudCreateAccount = createAccount;
  window.cloudSaveName = saveName;
  window.cloudEditName = editName;
  window.cloudCancelEdit = cancelEdit;
  window.cloudShowCreate = showCreate;
  window.cloudShowSignIn = showSignIn;
  window.cloudSignOut = signOut;
  window.cloudCloseModal = closeModal;
  window.cloudGetSession = () => session;
  window.cloudGetAccount = () => account;

  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
