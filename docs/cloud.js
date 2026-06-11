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
      : "";

  // bypass the IndexedDB fetch-shim so backend calls actually leave the browser
  const directFetch = window.sfDirectFetch || window.fetch.bind(window);
  const $ = (id) => document.getElementById(id);

  let supa = null;
  let session = null;   // Supabase session (null = signed out)
  let account = null;   // our backend's view: { email, plan, role, has_full_access }

  function client() {
    if (supa) return supa;
    if (!window.supabase || !window.supabase.createClient) return null;
    supa = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    return supa;
  }

  // ---- backend account / entitlement ----
  async function fetchAccount() {
    account = null;
    if (!session || !API_BASE) return;
    try {
      const r = await directFetch(API_BASE + "/api/auth/me", {
        headers: { Authorization: "Bearer " + session.access_token },
      });
      if (r.ok) account = await r.json();
    } catch (e) {
      /* backend not reachable (e.g. not running locally) — just no access info */
    }
  }

  function accessTag() {
    if (!account || !account.has_full_access) return "Free";
    if (account.role === "admin") return "Admin";
    if (account.plan === "comp") return "Full access";
    return "Pro";
  }

  // ---- UI ----
  function render() {
    const btn = $("accountbtn");
    if (!btn) return;
    if (session) {
      const email = (session.user && session.user.email) || "Account";
      btn.textContent = email.split("@")[0];
      btn.title = email + " — " + accessTag();
      btn.classList.add("signed-in");
    } else {
      btn.textContent = "Sign In";
      btn.title = "Sign in to sync across devices";
      btn.classList.remove("signed-in");
    }
  }

  function msg(text, kind) {
    const m = $("authmsg");
    if (m) { m.textContent = text || ""; m.className = "auth-msg" + (kind ? " " + kind : ""); }
  }

  function showModal() {
    const signedIn = !!session;
    $("authForm").style.display = signedIn ? "none" : "block";
    $("authAccount").style.display = signedIn ? "block" : "none";
    $("authTitle").textContent = signedIn ? "Your account" : "Sign in";
    if (signedIn) {
      $("authAcctEmail").textContent = (session.user && session.user.email) || "";
      $("authAcctTag").textContent = "Access: " + accessTag();
    } else {
      msg("");
      const e = $("authEmail"); if (e) setTimeout(() => e.focus(), 30);
    }
    $("authModal").style.display = "flex";
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

  async function signUp() {
    const email = ($("authEmail").value || "").trim();
    const pw = $("authPass").value || "";
    if (!email || !pw) return msg("Enter your email and password.", "err");
    if (pw.length < 6) return msg("Password must be at least 6 characters.", "err");
    const c = client(); if (!c) return msg("Sign-up is unavailable right now.", "err");
    msg("Creating your account…");
    const { data, error } = await c.auth.signUp({ email, password: pw });
    if (error) return msg(error.message, "err");
    if (data && data.session) closeModal();                 // email confirmation off
    else msg("Account created. Check your email to confirm, then sign in.", "ok");
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
    const btn = $("accountbtn");
    if (btn) btn.addEventListener("click", showModal);
    const pass = $("authPass");
    if (pass) pass.addEventListener("keydown", (e) => { if (e.key === "Enter") signIn(); });

    const c = client();
    if (!c) { render(); return; }   // supabase-js failed to load -> stay signed-out
    c.auth.getSession().then(({ data }) => onAuth(data ? data.session : null));
    c.auth.onAuthStateChange((_evt, s) => onAuth(s));
  }

  // expose for inline onclick handlers
  window.cloudSignIn = signIn;
  window.cloudSignUp = signUp;
  window.cloudSignOut = signOut;
  window.cloudCloseModal = closeModal;
  window.cloudGetSession = () => session;
  window.cloudGetAccount = () => account;

  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
