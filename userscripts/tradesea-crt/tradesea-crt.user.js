// ==UserScript==
// @name            Tradesea CRT · Candle Range Theory (1H–12H)
// @name:es         Tradesea CRT · Candle Range Theory (1H–12H)
// @namespace       https://github.com/xavieraijon/aijon-labs
// @version         1.4.0
// @description     Detects Candle Range Theory (CRT) setups from 1H to 12H and draws them as Horizontal Rays on Tradesea charts.
// @description:es  Detecta setups de Candle Range Theory (CRT) de 1H a 12H y los dibuja como Horizontal Rays en los gráficos de Tradesea.
// @author          AijonLabs
// @license         MIT
// @icon            data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iMTQiIGZpbGw9IiMyOTYyRkYiLz48bGluZSB4MT0iOCIgeTE9IjE4IiB4Mj0iNTYiIHkyPSIxOCIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjMiIHN0cm9rZS1kYXNoYXJyYXk9IjUgMyIvPjxsaW5lIHgxPSI4IiB5MT0iNDYiIHgyPSI1NiIgeTI9IjQ2IiBzdHJva2U9IiNmZmYiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWRhc2hhcnJheT0iNSAzIi8+PGxpbmUgeDE9IjMyIiB5MT0iOSIgeDI9IjMyIiB5Mj0iNTUiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48cmVjdCB4PSIyNCIgeT0iMjMiIHdpZHRoPSIxNiIgaGVpZ2h0PSIxOCIgcng9IjIiIGZpbGw9IiNmZmYiLz48L3N2Zz4K
// @homepageURL     https://github.com/xavieraijon/aijon-labs/tree/main/userscripts/tradesea-crt
// @supportURL      https://github.com/xavieraijon/aijon-labs/issues
// @updateURL       https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js
// @downloadURL     https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js
// @match           https://app.tradesea.ai/*
// @run-at          document-idle
// @noframes
// @grant           none
// ==/UserScript==

/*
 * Tradesea CRT — AijonLabs
 * ------------------------------------------------------------------------------------------------
 * Analysis tool only. It reads candles from the chart's own data feed and draws rays on the chart.
 * It never sends orders, never touches your account and never sends data anywhere.
 * Not affiliated with, endorsed by or supported by Tradesea or TradingView.
 * Nothing drawn by this script is financial advice. Trading futures involves substantial risk.
 *
 * Herramienta solo de análisis: lee velas del propio gráfico y dibuja rayos. No envía órdenes,
 * no toca tu cuenta ni envía datos a ningún sitio. Sin relación con Tradesea ni TradingView.
 * Nada de lo que dibuja es una recomendación de inversión.
 * ------------------------------------------------------------------------------------------------
 */

(function () {
  'use strict';

  /* ───────────────────────── Constants ───────────────────────── */
  const TIMEFRAMES = [
    { label: '12H', min: 720, color: '#E91E63' },
    { label: '8H',  min: 480, color: '#00897B' },
    { label: '6H',  min: 360, color: '#795548' },
    { label: '4H',  min: 240, color: '#FF9800' },
    { label: '3H',  min: 180, color: '#9C27B0' },
    { label: '2H',  min: 120, color: '#2962FF' },
    { label: '1H',  min: 60,  color: '#9E9E9E' },
  ];
  const CFG = {
    historyDays: 30,         // 1H history downloaded on start
    pollSeconds: 30,         // recalculation interval
    sessionStartHourNY: 18,  // CME session start (New York time)
    sessionHours: 23,        // session length (18:00 → 17:00 NY)
    legacyPrefix: 'CRT ',    // label prefix used by pre-1.3 versions (only used to clean old rays)
  };
  // Ray label: "2H High (Bearish)". The script recognises its own rays by this format.
  const LABEL_RE = /^(12H|8H|6H|4H|3H|2H|1H) (High|Low|50%) \((Bullish|Bearish)\)$/;
  const makeLabel = (tf, side, dir) => `${tf} ${side} (${dir === 'bull' ? 'Bullish' : 'Bearish'})`;
  const TEXT_COLOR = { bull: '#089981', bear: '#F23645' }; // label green / red; the line keeps its timeframe colour

  /* ───────────────────────── i18n ───────────────────────── */
  const STRINGS = {
    en: {
      waiting: 'Waiting for the chart…', unsupported: 'Unsupported timeframe (1H–12H only)', error: 'Error',
      tooltip: 'Candle Range Theory 1H–12H', drag: 'Drag to move', refresh: 'Recalculate now', settings: 'Settings',
      on: 'on', off: 'off', enable: 'Enable', disable: 'Disable and remove rays', modeAll: 'all', modeActive: 'active',
      title: 'CRT · settings', close: 'Close', secTf: 'Timeframes', all: 'All selected', active: 'Only the chart’s active timeframe',
      secShow: 'Show', showActive: 'Active (C2 closed)', showForming: 'Forming (C2 still open)', showMid: '50% level',
      secValid: 'Validity', invClose: 'Invalidate when a candle closes outside the range',
      maxAge: 'Max. age', bars: 'bars', resetPos: 'Reset position', resetAll: 'Restore defaults',
    },
    es: {
      waiting: 'Esperando al gráfico…', unsupported: 'Temporalidad no soportada (solo 1H–12H)', error: 'Error',
      tooltip: 'Candle Range Theory 1H–12H', drag: 'Arrastra para mover', refresh: 'Recalcular ahora', settings: 'Ajustes',
      on: 'on', off: 'off', enable: 'Activar', disable: 'Desactivar y borrar los rayos', modeAll: 'todas', modeActive: 'activa',
      title: 'CRT · ajustes', close: 'Cerrar', secTf: 'Temporalidades', all: 'Todas las marcadas', active: 'Solo la activa del gráfico',
      secShow: 'Mostrar', showActive: 'Activos (C2 cerrada)', showForming: 'En formación (C2 abierta)', showMid: 'Nivel 50 %',
      secValid: 'Validez', invClose: 'Invalidar si una vela cierra fuera del rango',
      maxAge: 'Antigüedad máx.', bars: 'velas', resetPos: 'Restablecer posición', resetAll: 'Valores por defecto',
    },
  };
  const VERSION = (typeof GM_info !== 'undefined' && GM_info.script && GM_info.script.version) || '1.4.0';
  const T = STRINGS[(navigator.language || 'en').toLowerCase().startsWith('es') ? 'es' : 'en'];

  /* ───────────────────────── Settings (persisted) ───────────────────────── */
  const LS_SETTINGS = 'crtTradesea.settings';
  const DEFAULTS = {
    enabled: true,
    mode: 'all',              // 'all' = selected timeframes | 'active' = the chart's current timeframe only
    tfs: Object.fromEntries(TIMEFRAMES.map((t) => [t.label, true])),
    showActive: true,         // C2 closed, target not reached yet
    showForming: true,        // C2 is the current (still open) candle
    showMid: false,           // 50% of C1's range
    invalidateOnClose: true,  // invalid once a later candle closes outside C1 on the swept side
    maxAgeBars: 30,           // ignore setups whose C2 is older than N bars of its timeframe
    pos: null,                // { left, top } of the badge
  };
  function loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem(LS_SETTINGS) || '{}');
      return { ...DEFAULTS, ...s, tfs: { ...DEFAULTS.tfs, ...(s.tfs || {}) } };
    } catch (e) { return { ...DEFAULTS, tfs: { ...DEFAULTS.tfs } }; }
  }
  function saveSettings() { try { localStorage.setItem(LS_SETTINGS, JSON.stringify(S)); } catch (e) { /* storage unavailable */ } }
  const S = loadSettings();

  /* ───────────────────────── State ───────────────────────── */
  if (window.__crtTradesea) window.__crtTradesea.stop(); // avoid duplicate instances

  const state = {
    timer: null,
    busy: false,
    pending: false,
    symbolInfo: new Map(),   // ticker → symbolInfo
    bars: new Map(),         // ticker → 1H bars
    drawn: new Map(),        // chart index → { sig, ids }
    hooked: new WeakSet(),   // charts with event subscriptions
    subs: [],                // [subject, callback] pairs, to unsubscribe on stop
    lastRun: null,
    lastCount: 0,
    note: '',
    error: null,
  };

  /* ───────────────────────── TradingView access ───────────────────────── */
  function getTV() {
    const ifr = document.querySelector('iframe[id^="tradingview_"]');
    const fw = ifr && ifr.contentWindow;
    if (!fw || !fw.tradingViewApi || !fw.ChartApiInstance) return null;
    const se = fw.ChartApiInstance._studyEngine;
    const df = se && se._externalDatafeed;
    if (!df || typeof df.getBars !== 'function') return null;
    return { api: fw.tradingViewApi, df };
  }

  function resolveSymbol(df, ticker) {
    if (state.symbolInfo.has(ticker)) return Promise.resolve(state.symbolInfo.get(ticker));
    return new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error('resolveSymbol timeout')), 10000);
      df.resolveSymbol(ticker, (si) => { clearTimeout(t); state.symbolInfo.set(ticker, si); res(si); },
        (e) => { clearTimeout(t); rej(new Error('resolveSymbol: ' + e)); });
    });
  }

  function getBars(df, si, fromSec, toSec, countBack) {
    return new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error('getBars timeout')), 15000);
      df.getBars(si, '60', { from: fromSec, to: toSec, countBack, firstDataRequest: true },
        (bars) => { clearTimeout(t); res(bars || []); },
        (e) => { clearTimeout(t); rej(new Error('getBars: ' + e)); });
    });
  }

  async function loadHourly(df, ticker) {
    const si = await resolveSymbol(df, ticker);
    const nowSec = Math.floor(Date.now() / 1000);
    const cached = state.bars.get(ticker);
    if (!cached || !cached.length) {
      const bars = await getBars(df, si, nowSec - CFG.historyDays * 86400, nowSec, CFG.historyDays * 24);
      state.bars.set(ticker, bars.slice().sort((a, b) => a.time - b.time));
    } else {
      const fresh = await getBars(df, si, nowSec - 3 * 86400, nowSec, 72);
      const m = new Map(cached.map((b) => [b.time, b]));
      for (const b of fresh) m.set(b.time, b);
      const merged = [...m.values()].sort((a, b) => a.time - b.time);
      state.bars.set(ticker, merged.slice(-CFG.historyDays * 24 - 48));
    }
    return state.bars.get(ticker);
  }

  function resolutionToMinutes(res) {
    const r = String(res).toUpperCase();
    if (/^\d+$/.test(r)) return Number(r);
    const m = r.match(/^(\d+)H$/);
    return m ? Number(m[1]) * 60 : null;
  }

  function hookChart(chart) {
    if (state.hooked.has(chart)) return;
    state.hooked.add(chart);
    const again = () => setTimeout(run, 300);
    for (const getSubj of [() => chart.onIntervalChanged(), () => chart.onSymbolChanged()]) {
      try { const subj = getSubj(); subj.subscribe(null, again); state.subs.push([subj, again]); } catch (e) { /* not available */ }
    }
  }

  /* ───────────────────────── Aggregation (aligned to the CME session) ───────────────────────── */
  const nyFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour12: false, hour: '2-digit', minute: '2-digit' });
  function nyHM(ms) {
    const p = nyFmt.formatToParts(new Date(ms));
    return [Number(p.find((x) => x.type === 'hour').value) % 24, Number(p.find((x) => x.type === 'minute').value)];
  }

  function aggregate(hourly, tfMin) {
    const now = Date.now();
    const map = new Map();
    for (const x of hourly) {
      const [h, mi] = nyHM(x.time);
      const off = ((h - CFG.sessionStartHourNY + 24) % 24) * 60 + mi;   // minutes since session start
      const sessionStart = x.time - off * 60000;
      const idx = Math.floor(off / tfMin);
      const start = sessionStart + idx * tfMin * 60000;
      const end = Math.min(start + tfMin * 60000, sessionStart + CFG.sessionHours * 3600000);
      const g = map.get(start);
      if (!g) map.set(start, { t: start, end, o: x.open, h: x.high, l: x.low, c: x.close });
      else { g.h = Math.max(g.h, x.high); g.l = Math.min(g.l, x.low); g.c = x.close; }
    }
    const out = [...map.values()].sort((a, b) => a.t - b.t);
    for (const b of out) b.closed = now >= b.end;
    return out;
  }

  /* ───────────────────────── CRT detection ─────────────────────────
   * C1 = range candle, C2 = the next candle.
   * Setup:      C2 sweeps exactly one extreme of C1 and closes (or currently trades) back inside C1.
   * Completed:  price reaches the opposite extreme of C1          → removed.
   * Invalid:    price goes beyond C2's sweep wick                  → removed.
   *             a later candle closes outside C1 on the swept side → removed (optional).
   */
  function detect(bars, tf) {
    const out = [];
    const n = bars.length;
    for (let i = Math.max(1, n - 1 - S.maxAgeBars); i < n; i++) {
      const c1 = bars[i - 1], c2 = bars[i];
      const sweptH = c2.h > c1.h, sweptL = c2.l < c1.l;
      if (sweptH === sweptL) continue;                    // none or both extremes swept
      if (!(c2.c < c1.h && c2.c > c1.l)) continue;        // C2 must close (or trade) back inside
      const dir = sweptL ? 'bull' : 'bear';
      const forming = !c2.closed;
      if (forming ? !S.showForming : !S.showActive) continue;
      const target = dir === 'bull' ? c1.h : c1.l;
      const inval = dir === 'bull' ? c2.l : c2.h;
      let alive = true;
      for (let j = i + 1; j < n; j++) {
        const x = bars[j];
        if (dir === 'bull' ? (x.l < inval || x.h >= target) : (x.h > inval || x.l <= target)) { alive = false; break; }
        if (S.invalidateOnClose && x.closed && (dir === 'bull' ? x.c < c1.l : x.c > c1.h)) { alive = false; break; }
      }
      if (!alive) continue;
      out.push({ tf: tf.label, color: tf.color, dir, forming, t: c1.t, high: c1.h, low: c1.l, mid: (c1.h + c1.l) / 2 });
    }
    return out;
  }

  function timeframesFor(chart) {
    if (S.mode === 'active') {
      const min = resolutionToMinutes(chart.resolution());
      const tf = TIMEFRAMES.find((t) => t.min === min);
      return tf ? [tf] : [];
    }
    return TIMEFRAMES.filter((t) => S.tfs[t.label]);
  }

  /* ───────────────────────── Drawing ───────────────────────── */
  function isOurShape(chart, s) {
    if (s.name !== 'horizontal_ray') return false;
    try {
      const txt = chart.getShapeById(s.id).getProperties().text || '';
      return LABEL_RE.test(txt) || txt.startsWith(CFG.legacyPrefix);
    } catch (e) { return false; }
  }

  function clearChart(chart) {
    let shapes = [];
    try { shapes = chart.getAllShapes(); } catch (e) { return; }
    for (const s of shapes) if (isOurShape(chart, s)) { try { chart.removeEntity(s.id); } catch (e) { /* already gone */ } }
  }

  async function drawChart(chart, idx, items, ticker) {
    const sig = ticker + '|' + S.showMid + '|' + JSON.stringify(items.map((i) => [i.tf, i.dir, i.forming, i.t, i.high, i.low]));
    const prev = state.drawn.get(idx);
    if (prev && prev.sig === sig) {
      let existing = new Set();
      try { existing = new Set(chart.getAllShapes().map((s) => s.id)); } catch (e) { /* ignore */ }
      if (prev.ids.every((id) => existing.has(id))) return; // nothing changed
    }
    clearChart(chart);
    const ids = [];
    for (const it of items) {
      const style = it.forming ? 2 : 0; // dashed while C2 is still open
      const lines = [['High', it.high, style], ['Low', it.low, style]];
      if (S.showMid) lines.push(['50%', it.mid, 1]);
      for (const [side, price, linestyle] of lines) {
        try {
          const id = await chart.createShape({ time: Math.floor(it.t / 1000), price }, {
            shape: 'horizontal_ray',
            text: makeLabel(it.tf, side, it.dir),
            overrides: {
              showLabel: true, textcolor: TEXT_COLOR[it.dir], linecolor: it.color, linewidth: 1, linestyle,
              horzLabelsAlign: 'right', vertLabelsAlign: side === 'Low' ? 'bottom' : 'top', fontsize: 11,
            },
          });
          if (id) ids.push(id);
        } catch (e) { /* skip a failed ray */ }
      }
    }
    state.drawn.set(idx, { sig, ids });
  }

  /* ───────────────────────── Main loop ───────────────────────── */
  async function run() {
    if (state.busy) { state.pending = true; return; }
    state.busy = true;
    try {
      const tv = getTV();
      if (!tv) { state.error = T.waiting; return; }
      const count = tv.api.chartsCount ? tv.api.chartsCount() : 1;
      let total = 0;
      let unsupported = false;
      for (let i = 0; i < count; i++) {
        const chart = tv.api.chart(i);
        hookChart(chart);
        if (!S.enabled) { clearChart(chart); state.drawn.delete(i); continue; }
        const tfs = timeframesFor(chart);
        if (S.mode === 'active' && !tfs.length) unsupported = true;
        const ticker = chart.symbol();
        const items = [];
        if (tfs.length) {
          const hourly = await loadHourly(tv.df, ticker);
          for (const tf of tfs) items.push(...detect(aggregate(hourly, tf.min), tf));
        }
        await drawChart(chart, i, items, ticker);
        total += items.length;
      }
      state.lastCount = total;
      state.lastRun = new Date();
      state.note = unsupported ? T.unsupported : '';
      state.error = null;
    } catch (e) {
      state.error = e && e.message ? e.message : String(e);
    } finally {
      state.busy = false;
      renderBadge();
      if (state.pending) { state.pending = false; run(); }
    }
  }

  function applyChange() { saveSettings(); state.drawn.clear(); renderPanel(); run(); }

  /* ───────────────────────── UI (Shadow DOM, isolated from the page's CSS) ───────────────────────── */
  const ICON_REFRESH = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
  const ICON_GEAR = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';

  const host = document.createElement('div');
  host.id = 'crt-tradesea-host';
  host.style.cssText = 'all:initial;display:block !important;visibility:visible !important;position:fixed;left:0;top:0;width:0;height:0;z-index:2147483000';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
      .badge { position: fixed; display: flex; align-items: center; gap: 4px; padding: 4px 6px 4px 12px;
        font-size: 13px; font-weight: 500; line-height: 1.4; color: #333;
        background: rgba(255,255,255,.96); border: 1px solid #c8c8c8; border-radius: 18px;
        box-shadow: 0 2px 6px rgba(0,0,0,.15); user-select: none; white-space: nowrap; }
      .handle { display: flex; align-items: center; gap: 8px; cursor: grab; padding-right: 4px; }
      .badge.dragging .handle { cursor: grabbing; }
      .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
      button { border: none; background: transparent; cursor: pointer; font: inherit; color: #2962FF; padding: 0 3px; }
      button:hover { text-decoration: underline; }
      button:focus-visible, input:focus-visible { outline: 2px solid #2962FF; outline-offset: 2px; }
      .badge button { min-width: 28px; height: 28px; border-radius: 14px; display: inline-flex;
        align-items: center; justify-content: center; line-height: 1; color: #444; padding: 0 6px; }
      .badge button:hover { background: #eef2ff; color: #2962FF; text-decoration: none; }
      .badge button.toggle { font-size: 12px; font-weight: 600; color: #2962FF; }
      .panel { position: fixed; width: 290px; padding: 10px 12px; font-size: 12px; color: #222;
        background: #fff; border: 1px solid #d0d0d0; border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.18); }
      .panel[hidden] { display: none; }
      .head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; margin-bottom: 8px; }
      .sec { margin: 8px 0; }
      .sec-title { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: #888; margin-bottom: 4px; }
      label { display: flex; align-items: center; gap: 6px; padding: 2px 0; cursor: pointer; }
      .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 2px 6px; margin-top: 4px; }
      .grid.disabled { opacity: .4; pointer-events: none; }
      .sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
      input[type=number] { width: 56px; padding: 2px 4px; font: inherit; border: 1px solid #ccc; border-radius: 4px; }
      .foot { display: flex; justify-content: space-between; gap: 8px; margin-top: 10px; padding-top: 8px; border-top: 1px solid #eee; }
      .brand { margin-top: 6px; font-size: 10px; color: #aaa; text-align: right; }
    </style>
    <div class="badge" role="toolbar" aria-label="CRT">
      <span class="handle" title="${T.drag}"><span class="dot"></span><span class="label"></span></span>
      <button class="refresh" title="${T.refresh}" aria-label="${T.refresh}">${ICON_REFRESH}</button>
      <button class="gear" title="${T.settings}" aria-label="${T.settings}">${ICON_GEAR}</button>
      <button class="toggle"></button>
    </div>
    <div class="panel" role="dialog" aria-label="${T.title}" hidden>
      <div class="head"><span>${T.title}</span><button class="close" title="${T.close}" aria-label="${T.close}">✕</button></div>
      <div class="sec">
        <div class="sec-title">${T.secTf}</div>
        <label><input type="radio" name="mode" value="all"> ${T.all}</label>
        <div class="grid tfs"></div>
        <label><input type="radio" name="mode" value="active"> ${T.active}</label>
      </div>
      <div class="sec">
        <div class="sec-title">${T.secShow}</div>
        <label><input type="checkbox" class="showActive"> ${T.showActive}</label>
        <label><input type="checkbox" class="showForming"> ${T.showForming}</label>
        <label><input type="checkbox" class="showMid"> ${T.showMid}</label>
      </div>
      <div class="sec">
        <div class="sec-title">${T.secValid}</div>
        <label><input type="checkbox" class="invClose"> ${T.invClose}</label>
      </div>
      <div class="sec">
        <label>${T.maxAge} <input type="number" class="maxAge" min="1" max="200"> ${T.bars}</label>
      </div>
      <div class="foot">
        <button class="resetPos">${T.resetPos}</button>
        <button class="resetAll">${T.resetAll}</button>
      </div>
      <div class="brand">AijonLabs · v${VERSION}</div>
    </div>`;

  const $ = (sel) => root.querySelector(sel);
  const badge = $('.badge'), panel = $('.panel'), dot = $('.dot'), label = $('.label');

  const grid = $('.tfs');
  for (const tf of TIMEFRAMES) {
    const l = document.createElement('label');
    l.innerHTML = `<input type="checkbox" data-tf="${tf.label}"><span class="sw" style="background:${tf.color}"></span>${tf.label}`;
    grid.appendChild(l);
  }

  function renderPanel() {
    root.querySelectorAll('input[name=mode]').forEach((r) => { r.checked = r.value === S.mode; });
    grid.classList.toggle('disabled', S.mode !== 'all');
    grid.querySelectorAll('input[data-tf]').forEach((c) => { c.checked = !!S.tfs[c.dataset.tf]; });
    $('.showActive').checked = S.showActive;
    $('.showForming').checked = S.showForming;
    $('.showMid').checked = S.showMid;
    $('.invClose').checked = S.invalidateOnClose;
    $('.maxAge').value = S.maxAgeBars;
  }

  function renderBadge() {
    const hhmm = state.lastRun ? state.lastRun.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--';
    const modeTxt = S.mode === 'active' ? T.modeActive : T.modeAll;
    dot.style.background = !S.enabled ? '#bbb' : state.error ? '#F44336' : state.note ? '#FFC107' : '#4CAF50';
    label.textContent = S.enabled ? `CRT (${modeTxt}) · ${state.lastCount} · ${hhmm}` : `CRT · ${T.off}`;
    const toggle = $('.toggle');
    toggle.textContent = S.enabled ? T.off : T.on;
    toggle.title = S.enabled ? T.disable : T.enable;
    badge.title = state.error ? `${T.error}: ${state.error}` : state.note || T.tooltip;
  }

  // Panel events
  root.querySelectorAll('input[name=mode]').forEach((r) => r.addEventListener('change', () => { S.mode = r.value; applyChange(); }));
  grid.addEventListener('change', (e) => { const tf = e.target.dataset.tf; if (tf) { S.tfs[tf] = e.target.checked; applyChange(); } });
  $('.showActive').addEventListener('change', (e) => { S.showActive = e.target.checked; applyChange(); });
  $('.showForming').addEventListener('change', (e) => { S.showForming = e.target.checked; applyChange(); });
  $('.showMid').addEventListener('change', (e) => { S.showMid = e.target.checked; applyChange(); });
  $('.invClose').addEventListener('change', (e) => { S.invalidateOnClose = e.target.checked; applyChange(); });
  $('.maxAge').addEventListener('change', (e) => {
    S.maxAgeBars = Math.max(1, Math.min(200, parseInt(e.target.value, 10) || DEFAULTS.maxAgeBars));
    applyChange();
  });
  $('.resetPos').addEventListener('click', () => { S.pos = null; saveSettings(); placeBadge(); placePanel(); });
  $('.resetAll').addEventListener('click', () => {
    const pos = S.pos;
    Object.assign(S, { ...DEFAULTS, tfs: { ...DEFAULTS.tfs }, pos });
    applyChange();
  });
  $('.close').addEventListener('click', () => { panel.hidden = true; });
  $('.gear').addEventListener('click', () => { panel.hidden = !panel.hidden; if (!panel.hidden) { renderPanel(); placePanel(); } });
  $('.refresh').addEventListener('click', () => { state.drawn.clear(); run(); });
  $('.toggle').addEventListener('click', () => { S.enabled = !S.enabled; applyChange(); });
  root.addEventListener('keydown', (e) => { if (e.key === 'Escape') panel.hidden = true; });

  // Position & drag
  function clampPos(left, top) {
    const r = badge.getBoundingClientRect();
    return {
      left: Math.max(0, Math.min(window.innerWidth - r.width, left)),
      top: Math.max(0, Math.min(window.innerHeight - r.height, top)),
    };
  }
  function placeBadge() {
    if (S.pos) {
      const p = clampPos(S.pos.left, S.pos.top);
      Object.assign(badge.style, { left: p.left + 'px', top: p.top + 'px', bottom: 'auto' });
    } else {
      Object.assign(badge.style, { left: '92px', top: 'auto', bottom: '44px' });
    }
  }
  function placePanel() {
    if (panel.hidden) return;
    const b = badge.getBoundingClientRect();
    const pw = panel.offsetWidth, ph = panel.offsetHeight;
    const below = b.top < window.innerHeight / 2;
    const top = below ? b.bottom + 6 : b.top - ph - 6;
    const left = Math.max(4, Math.min(window.innerWidth - pw - 4, b.left));
    Object.assign(panel.style, { left: left + 'px', top: Math.max(4, top) + 'px' });
  }

  const handle = $('.handle');
  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const r = badge.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    badge.classList.add('dragging');
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const p = clampPos(ev.clientX - dx, ev.clientY - dy);
      Object.assign(badge.style, { left: p.left + 'px', top: p.top + 'px', bottom: 'auto' });
      placePanel();
    };
    const up = (ev) => {
      handle.releasePointerCapture(ev.pointerId);
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      badge.classList.remove('dragging');
      const rr = badge.getBoundingClientRect();
      S.pos = { left: Math.round(rr.left), top: Math.round(rr.top) };
      saveSettings();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    e.preventDefault();
  });
  const onResize = () => { placeBadge(); placePanel(); };

  /* ───────────────────────── Start ───────────────────────── */
  function start() {
    if (!document.body) return setTimeout(start, 500);
    document.body.appendChild(host);
    placeBadge();
    renderPanel();
    renderBadge();
    window.addEventListener('resize', onResize);
    run();
    state.timer = setInterval(run, CFG.pollSeconds * 1000);
  }

  window.__crtTradesea = {
    stop() {
      clearInterval(state.timer);
      window.removeEventListener('resize', onResize);
      for (const [subj, cb] of state.subs) { try { subj.unsubscribe(null, cb); } catch (e) { /* ignore */ } }
      host.remove();
    },
    run, state, settings: S,
  };

  start();
})();
