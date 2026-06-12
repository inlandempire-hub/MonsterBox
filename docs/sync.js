/*
 * sync.js — optional cloud sync of the compendium for signed-in Pro users.
 *
 * Local-first by design: IndexedDB stays the source of truth the UI reads from;
 * this layer MIRRORS it to (and from) the server in the background. Signed out,
 * free, or no server reachable -> it's a no-op and the app is unchanged.
 *
 * - On sign-in (full access): reconcile() does a two-way union/last-write-wins
 *   merge so the device shows the combined library and both sides match.
 * - On a local change: the write is mirrored to the server (debounced).
 * - engine.js fires window.sfOnWrite(op, payload) after each local statblock
 *   write; cloud.js drives window.onCloudAuthChange on sign-in/out.
 */
(function () {
  "use strict";

  const API_BASE =
    location.hostname === "127.0.0.1" || location.hostname === "localhost"
      ? "http://127.0.0.1:8090"
      : "";   // production backend URL goes here once deployed
  const directFetch = window.sfDirectFetch || window.fetch.bind(window);

  let status = "off";          // off | syncing | synced | error
  let reconciling = false;
  let flushTimer = null;
  const dirty = new Set();      // client ids with a pending upload
  const removed = new Set();    // client ids pending delete

  const session = () => (window.cloudGetSession ? window.cloudGetSession() : null);
  const account = () => (window.cloudGetAccount ? window.cloudGetAccount() : null);
  const token = () => { const s = session(); return s && s.access_token; };
  function entitled() {
    const a = account();
    return !!(API_BASE && session() && a && a.has_full_access);
  }
  function setStatus(s) {
    status = s;
    if (typeof window.onSyncStatus === "function") { try { window.onSyncStatus(s); } catch (e) {} }
  }
  window.sfSyncStatus = () => status;
  window.sfSyncNow = () => reconcile();

  // ---- server I/O (real backend, bypassing the local shim) ----
  const hdr = (extra) => Object.assign({ Authorization: "Bearer " + token() }, extra || {});
  async function serverList() {
    const r = await directFetch(API_BASE + "/api/statblocks", { headers: hdr() });
    if (!r.ok) throw new Error("list " + r.status);
    return await r.json();   // [{ id, name, data, updated_at }]
  }
  async function serverPut(sb) {
    const r = await directFetch(API_BASE + "/api/statblocks/" + encodeURIComponent(sb.id), {
      method: "PUT", headers: hdr({ "Content-Type": "application/json" }),
      body: JSON.stringify({ id: sb.id, name: sb.name || "", data: sb }),
    });
    if (!r.ok) throw new Error("put " + r.status);
  }
  async function serverDelete(id) {
    await directFetch(API_BASE + "/api/statblocks/" + encodeURIComponent(id), { method: "DELETE", headers: hdr() });
  }
  async function serverClear() {
    await directFetch(API_BASE + "/api/statblocks", { method: "DELETE", headers: hdr() });
  }

  // ---- local I/O (via the IndexedDB fetch-shim) ----
  const localList = async () => await (await fetch("/api/statblocks")).json();
  async function localGet(id) {
    const r = await fetch("/api/statblocks/" + encodeURIComponent(id));
    return r.ok ? await r.json() : null;
  }
  async function localApply(sb) {
    window._sfApplyingRemote = true;   // don't echo this back to the server
    try {
      await fetch("/api/statblocks/" + encodeURIComponent(sb.id), {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sb),
      });
    } finally { window._sfApplyingRemote = false; }
  }

  const ts = (x) => {
    const v = x && x.updated_at;
    if (v == null) return 0;
    const n = typeof v === "number" ? v : Date.parse(v);
    return Number.isFinite(n) ? n : 0;
  };

  // ---- two-way reconcile (sign-in / manual) ----
  async function reconcile() {
    if (!entitled() || reconciling) return;
    reconciling = true; setStatus("syncing");
    try {
      const [server, local] = await Promise.all([serverList(), localList()]);
      const sMap = new Map(server.map((r) => [r.id, r]));     // r.data = full sb
      const lMap = new Map(local.map((sb) => [sb.id, sb]));
      for (const [id, sb] of lMap) {                          // local -> server
        const s = sMap.get(id);
        if (!s || ts(sb) > ts(s.data)) await serverPut(sb);
      }
      for (const [id, s] of sMap) {                           // server -> local
        const sb = lMap.get(id);
        const sdata = Object.assign({}, s.data); sdata.id = id;
        if (!sb || ts(sdata) > ts(sb)) await localApply(sdata);
      }
      if (typeof window.loadLibrary === "function") window.loadLibrary();
      setStatus("synced");
    } catch (e) {
      console.warn("[sync] reconcile failed:", e.message || e);
      setStatus("error");
    } finally { reconciling = false; }
  }

  // ---- live mirroring of local changes (debounced) ----
  function scheduleFlush() {
    if (flushTimer) clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, 1200);
  }
  async function flush() {
    flushTimer = null;
    if (!entitled() || (!dirty.size && !removed.size)) return;
    setStatus("syncing");
    try {
      const dels = [...removed]; removed.clear();
      for (const id of dels) await serverDelete(id);
      const ups = [...dirty]; dirty.clear();
      for (const id of ups) { const sb = await localGet(id); if (sb) await serverPut(sb); }
      setStatus("synced");
    } catch (e) {
      console.warn("[sync] flush failed:", e.message || e);
      setStatus("error");
    }
  }

  // engine.js -> after a local statblock write
  window.sfOnWrite = function (op, payload) {
    if (!entitled()) return;
    if (op === "upsert" && payload && payload.id) { removed.delete(payload.id); dirty.add(payload.id); scheduleFlush(); }
    else if (op === "delete" && payload && payload.id) { dirty.delete(payload.id); removed.add(payload.id); scheduleFlush(); }
    else if (op === "clear") { dirty.clear(); removed.clear(); serverClear().then(() => setStatus("synced")).catch(() => setStatus("error")); }
    else if (op === "bulk") reconcile();
  };

  // cloud.js -> on sign-in / sign-out
  window.onCloudAuthChange = function () {
    if (entitled()) reconcile();
    else setStatus("off");
  };
})();
