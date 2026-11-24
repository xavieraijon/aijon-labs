// ==UserScript==
// @name            Tradesea CRT · Candle Range Theory
// @name:es         Tradesea CRT · Candle Range Theory
// @namespace       https://github.com/xavieraijon/aijon-labs
// @version         1.6.0
// @description     Draws Candle Range Theory (CRT) setups as Horizontal Rays on Tradesea charts, on whatever timeframe each chart shows (2D, 10H, 33D…), plus any extra timeframes you add.
// @description:es  Dibuja los setups de Candle Range Theory (CRT) como Horizontal Rays en los gráficos de Tradesea, en la temporalidad que tenga cada gráfico (2D, 10H, 33D…), más las temporalidades extra que añadas.
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
 * Analysis tool only. It reads candles from the chart and its data feed and draws rays on the chart.
 * It never sends orders, never touches your account and never sends data anywhere.
 * Not affiliated with, endorsed by or supported by Tradesea or TradingView.
 * Nothing drawn by this script is financial advice. Trading futures involves substantial risk.
 *
 * Herramienta solo de análisis: lee velas del gráfico y dibuja rayos. No envía órdenes,
 * no toca tu cuenta ni envía datos a ningún sitio. Sin relación con Tradesea ni TradingView.
 * Nada de lo que dibuja es una recomendación de inversión.
 * ------------------------------------------------------------------------------------------------
 */

(function () {
  'use strict';

  /* ───────────────────────── Timeframes ─────────────────────────
   * Each chart ALWAYS gets the setups of its own timeframe, whatever it is, read from the candles the
   * chart itself draws. Optionally, extra timeframes from this list are added on top. Extra intraday
   * timeframes are built from a base resolution of the data feed, aligned to the CME session (18:00
   * New York) exactly like Tradesea's candles; D and W come straight from the feed and M is built
   * from daily candles.
   */
  const TIMEFRAMES = [
    { label: '15m', min: 15,  base: '15', color: '#00BCD4' },
    { label: '30m', min: 30,  base: '15', color: '#8BC34A' },
    { label: '1H',  min: 60,  base: '60', color: '#9E9E9E' },
    { label: '2H',  min: 120, base: '60', color: '#2962FF' },
    { label: '3H',  min: 180, base: '60', color: '#9C27B0' },
    { label: '4H',  min: 240, base: '60', color: '#FF9800' },
    { label: '6H',  min: 360, base: '60', color: '#795548' },
    { label: '8H',  min: 480, base: '60', color: '#00897B' },
    { label: '12H', min: 720, base: '60', color: '#E91E63' },
    { label: 'D',   period: 'D', base: '1D', color: '#3F51B5' },
    { label: 'W',   period: 'W', base: '1W', color: '#455A64' },
    { label: 'M',   period: 'M', base: '1D', color: '#212121' },
  ];
  const CHART_TF_COLOR = '#5C6BC0'; // chart timeframes outside the list above (2D, 10H, 33D…)

  // Data-feed resolutions the script downloads for extra timeframes (and '1D' to know when a
  // multi-day chart candle has closed): history on start, then a small refresh window.
  const BASES = {
    '15': { countBack: 960, days: 10,   refreshDays: 2,  minRefreshSec: 25 },
    '60': { countBack: 720, days: 30,   refreshDays: 3,  minRefreshSec: 25 },
    '1D': { countBack: 800, days: 1200, refreshDays: 10, minRefreshSec: 60 },
    '1W': { countBack: 150, days: 1100, refreshDays: 30, minRefreshSec: 60 },
  };

  const CFG = {
    pollSeconds: 15,         // recalculation interval
    sessionStartHourNY: 18,  // CME session start (New York time)
    sessionHours: 23,        // session length (18:00 → 17:00 NY)
    legacyPrefix: 'CRT ',    // label prefix used by pre-1.3 versions (only used to clean old rays)
  };
  const H = 3600000;
  const DAY = 24 * H;

  // Ray label: "2H High (Bearish)", "33D Low (Bullish)". The script recognises its own rays by this format.
  const LABEL_RE = /^(?=\w)\d*[A-Za-z]* (High|Low|50%) \((Bullish|Bearish)\)$/;
  const makeLabel = (tf, side, dir) => `${tf} ${side} (${dir === 'bull' ? 'Bullish' : 'Bearish'})`;
  const TEXT_COLOR = { bull: '#089981', bear: '#F23645' }; // label green / red; the line keeps its timeframe colour

  /* ───────────────────────── i18n ───────────────────────── */
  const STRINGS = {
    en: {
      waiting: 'Waiting for the chart…', error: 'Error', tooltip: 'Candle Range Theory on the chart’s timeframe',
      drag: 'Drag to move', refresh: 'Recalculate now', settings: 'Settings', on: 'on', off: 'off',
      enable: 'Enable', disable: 'Disable and remove rays', title: 'CRT · settings', close: 'Close',
      secTf: 'Timeframes', chartTf: 'The chart’s own timeframe, always (any: 2D, 10H, 33D…)',
      extra: 'Also add ranges from:', from: 'From', to: 'to', none: 'None',
      secShow: 'Show', showActive: 'Active (C2 closed)', showForming: 'Forming (C2 still open)', showMid: '50% level',
      secValid: 'Validity', invClose: 'Invalidate when a candle closes outside the range',
      maxAge: 'Max. age', bars: 'bars', resetPos: 'Reset position', resetAll: 'Restore defaults',
    },
    es: {
      waiting: 'Esperando al gráfico…', error: 'Error', tooltip: 'Candle Range Theory en la temporalidad del gráfico',
      drag: 'Arrastra para mover', refresh: 'Recalcular ahora', settings: 'Ajustes', on: 'on', off: 'off',
      enable: 'Activar', disable: 'Desactivar y borrar los rayos', title: 'CRT · ajustes', close: 'Cerrar',
      secTf: 'Temporalidades', chartTf: 'La del propio gráfico, siempre (cualquiera: 2D, 10H, 33D…)',
      extra: 'Añadir también rangos de:', from: 'Desde', to: 'hasta', none: 'Ninguna',
      secShow: 'Mostrar', showActive: 'Activos (C2 cerrada)', showForming: 'En formación (C2 abierta)', showMid: 'Nivel 50 %',
      secValid: 'Validez', invClose: 'Invalidar si una vela cierra fuera del rango',
      maxAge: 'Antigüedad máx.', bars: 'velas', resetPos: 'Restablecer posición', resetAll: 'Valores por defecto',
    },
  };
  const VERSION = (typeof GM_info !== 'undefined' && GM_info.script && GM_info.script.version) || '1.6.0';
  const T = STRINGS[(navigator.language || 'en').toLowerCase().startsWith('es') ? 'es' : 'en'];

  /* ───────────────────────── Settings (persisted) ───────────────────────── */
  const LS_SETTINGS = 'crtTradesea.settings';
  const SETTINGS_VERSION = 2;
  const DEFAULTS = {
    v: SETTINGS_VERSION,
    enabled: true,
    tfs: Object.fromEntries(TIMEFRAMES.map((t) => [t.label, false])), // extra timeframes (none by default)
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
      if (s.v !== SETTINGS_VERSION) { delete s.mode; delete s.tfs; s.v = SETTINGS_VERSION; } // ≤1.5: the chart's timeframe is now automatic
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
    data: new Map(),         // `${ticker}|${base}` → { bars, fetchedAt }
    drawn: new Map(),        // chart index → { sig, ids }
    hooked: new WeakSet(),   // charts with event subscriptions
    subs: [],                // [subject, callback] pairs, to unsubscribe on stop
    chartTfs: [],            // labels of the charts' timeframes, for the badge
    lastRun: null,
    lastCount: 0,
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

  function getBars(df, si, resolution, fromSec, toSec, countBack) {
    return new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error('getBars timeout')), 15000);
      df.getBars(si, resolution, { from: fromSec, to: toSec, countBack, firstDataRequest: true },
        (bars) => { clearTimeout(t); res(bars || []); },
        (e) => { clearTimeout(t); rej(new Error(`getBars ${resolution}: ${e}`)); });
    });
  }

  async function loadBase(df, ticker, base, runCache) {
    const key = `${ticker}|${base}`;
    if (runCache.has(key)) return runCache.get(key);
    const cfg = BASES[base];
    const si = await resolveSymbol(df, ticker);
    const nowSec = Math.floor(Date.now() / 1000);
    const cached = state.data.get(key);
    let bars;
    if (!cached) {
      bars = (await getBars(df, si, base, nowSec - cfg.days * 86400, nowSec, cfg.countBack)).slice().sort((a, b) => a.time - b.time);
    } else if (Date.now() - cached.fetchedAt < cfg.minRefreshSec * 1000) {
      bars = cached.bars;
    } else {
      const want = Math.ceil((cfg.countBack * cfg.refreshDays) / cfg.days) + 5;
      const fresh = await getBars(df, si, base, nowSec - cfg.refreshDays * 86400, nowSec, want);
      const m = new Map(cached.bars.map((b) => [b.time, b]));
      for (const b of fresh) m.set(b.time, b);
      bars = [...m.values()].sort((a, b) => a.time - b.time).slice(-(cfg.countBack + 100));
    }
    if (!cached || cached.bars !== bars) state.data.set(key, { bars, fetchedAt: Date.now() });
    runCache.set(key, bars);
    return bars;
  }

  function hookChart(chart) {
    if (state.hooked.has(chart)) return;
    state.hooked.add(chart);
    const again = () => setTimeout(run, 300);
    for (const getSubj of [() => chart.onIntervalChanged(), () => chart.onSymbolChanged(), () => chart.onDataLoaded()]) {
      try { const subj = getSubj(); subj.subscribe(null, again); state.subs.push([subj, again]); } catch (e) { /* not available */ }
    }
  }

  /* ───────────────────────── Time helpers ───────────────────────── */
  const nyFmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  function nyParts(ms) {
    const o = {};
    for (const p of nyFmt.formatToParts(new Date(ms))) o[p.type] = p.value;
    return { y: +o.year, mo: +o.month, d: +o.day, h: +o.hour % 24, mi: +o.minute };
  }
  // Start of the CME session (18:00 New York) that contains ms.
  function sessionStartOf(ms) {
    const p = nyParts(ms);
    const off = ((p.h - CFG.sessionStartHourNY + 24) % 24) * 60 + p.mi;
    return ms - (ms % 60000) - off * 60000;
  }

  /* ───────────────────────── The chart's own timeframe ─────────────────────────
   * Resolution strings: "15" (minutes), "600" (10H), "30S", "2D", "33D", "1W", "3M"…
   */
  function parseResolution(res) {
    const r = String(res).toUpperCase();
    let m;
    if (/^\d+$/.test(r)) {
      const n = Number(r);
      return { unit: 'min', n, label: n % 60 === 0 ? `${n / 60}H` : `${n}m` };
    }
    if ((m = r.match(/^(\d*)([SDWM])$/))) {
      const n = Number(m[1] || 1);
      const unit = m[2];
      if (unit === 'S') return { unit, n, label: `${n}s` };
      return { unit, n, label: n === 1 ? unit : `${n}${unit}` };
    }
    return { unit: 'other', n: 1, label: r };
  }

  // Candles the chart itself draws, with their open/closed state.
  async function chartBars(chart, df, ticker, runCache) {
    const res = parseResolution(chart.resolution());
    const exp = await chart.exportData({ includeTime: true, includeSeries: true, includedStudies: [] });
    const rows = (exp && exp.data) || [];
    const bars = rows
      .filter((r) => r[0] != null && r[2] != null && r[3] != null && r[4] != null)
      .map((r) => ({ s: r[0] * 1000, o: r[1], h: r[2], l: r[3], c: r[4], closed: true }));
    if (!bars.length) return { res, bars };
    bars[bars.length - 1].closed = await lastBarClosed(bars[bars.length - 1].s, res, df, ticker, runCache);
    return { res, bars };
  }

  // Has the chart's latest candle finished?
  async function lastBarClosed(start, res, df, ticker, runCache) {
    const now = Date.now();
    if (res.unit === 'S' || res.unit === 'min') {
      const len = res.unit === 'S' ? res.n * 1000 : res.n * 60000;
      const sessionEnd = sessionStartOf(start) + CFG.sessionHours * H;
      return now >= Math.min(start + len, sessionEnd);
    }
    if (res.unit === 'D') {
      // count the trading days that have started since the candle opened, using the feed's daily candles
      const daily = await loadBase(df, ticker, '1D', runCache);
      const inBar = daily.filter((x) => x.time - 7 * H >= start - H); // daily time = midnight Chicago; session opens 7 h earlier
      if (inBar.length < res.n) return false;
      return now >= inBar[inBar.length - 1].time + 16 * H;            // that trading day ends at 17:00 New York
    }
    if (res.unit === 'W') return now >= start + (res.n - 1) * 7 * DAY + 5 * DAY - H; // Sunday 18:00 → Friday 17:00 NY
    if (res.unit === 'M') {
      const p = nyParts(start + 6 * H); // trade date of the first session
      return now >= Date.UTC(p.y, p.mo - 1 + res.n, 1) - 2 * H;
    }
    return false; // unknown kind of candle (ticks, ranges…): treat the latest one as still forming
  }

  /* ───────────────────────── Extra timeframes (from the data feed) ───────────────────────── */
  function aggregate(base, tfMin) {
    const now = Date.now();
    const map = new Map();
    for (const x of base) {
      const ss = sessionStartOf(x.time);
      const off = (x.time - ss) / 60000;
      const start = ss + Math.floor(off / tfMin) * tfMin * 60000;
      const end = Math.min(start + tfMin * 60000, ss + CFG.sessionHours * H);
      const g = map.get(start);
      if (!g) map.set(start, { s: start, end, o: x.open, h: x.high, l: x.low, c: x.close });
      else { g.h = Math.max(g.h, x.high); g.l = Math.min(g.l, x.low); g.c = x.close; }
    }
    const out = [...map.values()].sort((a, b) => a.s - b.s);
    for (const b of out) b.closed = now >= b.end;
    return out;
  }

  // D and W from the feed: their time is midnight Chicago of the trade date (Monday for W); the
  // session really starts 7 hours earlier (18:00 New York) and the day ends 16 hours later (17:00 NY).
  function periodBars(base, period) {
    const now = Date.now();
    const toBar = (x) => ({ s: x.time - 7 * H, o: x.open, h: x.high, l: x.low, c: x.close });
    if (period === 'D' || period === 'W') {
      return base.map((x) => {
        const b = toBar(x);
        b.end = x.time + (period === 'D' ? 16 * H : 4 * DAY + 16 * H);
        b.closed = now >= b.end;
        return b;
      });
    }
    const map = new Map(); // M: daily candles grouped by the month of their trade date
    for (const x of base) {
      const d = new Date(x.time);
      const key = d.getUTCFullYear() * 12 + d.getUTCMonth();
      const g = map.get(key);
      if (!g) {
        const b = toBar(x);
        b.end = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) - 2 * H;
        map.set(key, b);
      } else { g.h = Math.max(g.h, x.high); g.l = Math.min(g.l, x.low); g.c = x.close; }
    }
    const out = [...map.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]);
    for (const b of out) b.closed = now >= b.end;
    return out;
  }

  const buildBars = (tf, base) => (tf.period ? periodBars(base, tf.period) : aggregate(base, tf.min));

  /* ───────────────────────── CRT detection ─────────────────────────
   * C1 = range candle, C2 = the next candle.
   * Setup:      C2 sweeps exactly one extreme of C1 and closes (or currently trades) back inside C1.
   * Completed:  price reaches the opposite extreme of C1          → removed.
   * Invalid:    price goes beyond C2's sweep wick                  → removed.
   *             a later candle closes outside C1 on the swept side → removed (optional).
   */
  function detect(bars, label, color, fromChart) {
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
      out.push({ tf: label, color, dir, forming, fromChart, s: c1.s, high: c1.h, low: c1.l, mid: (c1.h + c1.l) / 2 });
    }
    return out;
  }

  /* ───────────────────────── Drawing ───────────────────────── */
  // Where a ray starts. Rays of the chart's own timeframe start exactly on their C1 candle. Rays of
  // extra timeframes start at the real start of C1; on D/W/M charts they start at the session that
  // contains it, so they land on the right daily candle.
  function shapeTime(item, periodChart) {
    if (item.fromChart || !periodChart) return Math.floor(item.s / 1000);
    return Math.floor(sessionStartOf(item.s) / 1000);
  }

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

  async function drawChart(chart, idx, items, ticker, resolution) {
    const periodChart = /^\d*[DWM]$/i.test(String(resolution));
    const sig = [ticker, resolution, S.showMid, JSON.stringify(items.map((i) => [i.tf, i.dir, i.forming, i.s, i.high, i.low]))].join('|');
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
          const id = await chart.createShape({ time: shapeTime(it, periodChart), price }, {
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
      const runCache = new Map();
      const chartTfs = [];
      let total = 0;
      for (let i = 0; i < count; i++) {
        const chart = tv.api.chart(i);
        hookChart(chart);
        if (!S.enabled) { clearChart(chart); state.drawn.delete(i); continue; }
        const ticker = chart.symbol();
        const resolution = chart.resolution();
        // 1) the chart's own timeframe, always
        const { res, bars } = await chartBars(chart, tv.df, ticker, runCache);
        const preset = TIMEFRAMES.find((t) => t.label === res.label);
        const items = detect(bars, res.label, preset ? preset.color : CHART_TF_COLOR, true);
        chartTfs.push(res.label);
        // 2) extra timeframes, if any (skipping the chart's own)
        for (const tf of TIMEFRAMES) {
          if (!S.tfs[tf.label] || tf.label === res.label) continue;
          const base = await loadBase(tv.df, ticker, tf.base, runCache);
          items.push(...detect(buildBars(tf, base), tf.label, tf.color, false));
        }
        await drawChart(chart, i, items, ticker, resolution);
        total += items.length;
      }
      state.chartTfs = [...new Set(chartTfs)];
      state.lastCount = total;
      state.lastRun = new Date();
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
  const tfOptions = TIMEFRAMES.map((t) => `<option value="${t.label}">${t.label}</option>`).join('');
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
      button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid #2962FF; outline-offset: 2px; }
      .badge button { min-width: 28px; height: 28px; border-radius: 14px; display: inline-flex;
        align-items: center; justify-content: center; line-height: 1; color: #444; padding: 0 6px; }
      .badge button:hover { background: #eef2ff; color: #2962FF; text-decoration: none; }
      .badge button.toggle { font-size: 12px; font-weight: 600; color: #2962FF; }
      .panel { position: fixed; width: 330px; padding: 10px 12px; font-size: 12px; color: #222;
        background: #fff; border: 1px solid #d0d0d0; border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.18); }
      .panel[hidden] { display: none; }
      .head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; margin-bottom: 8px; }
      .sec { margin: 8px 0; }
      .sec-title { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: #888; margin-bottom: 4px; }
      label { display: flex; align-items: center; gap: 6px; padding: 2px 0; cursor: pointer; }
      .always { display: flex; align-items: center; gap: 6px; padding: 2px 0; }
      .check { color: #089981; font-weight: 700; width: 13px; text-align: center; }
      .extra { margin-top: 6px; }
      .range { display: flex; align-items: center; gap: 6px; margin: 4px 0; }
      select { font: inherit; padding: 1px 2px; border: 1px solid #ccc; border-radius: 4px; background: #fff; }
      .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 2px 6px; }
      .sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }
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
        <div class="always"><span class="check">✓</span>${T.chartTf}</div>
        <div class="extra">
          <div>${T.extra}</div>
          <div class="range">${T.from} <select class="from">${tfOptions}</select> ${T.to} <select class="to">${tfOptions}</select>
            <button class="noneBtn">${T.none}</button></div>
          <div class="grid tfs"></div>
        </div>
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
    grid.querySelectorAll('input[data-tf]').forEach((c) => { c.checked = !!S.tfs[c.dataset.tf]; });
    const on = TIMEFRAMES.filter((t) => S.tfs[t.label]);
    $('.from').value = (on[0] || TIMEFRAMES[0]).label;
    $('.to').value = (on[on.length - 1] || TIMEFRAMES[0]).label;
    $('.showActive').checked = S.showActive;
    $('.showForming').checked = S.showForming;
    $('.showMid').checked = S.showMid;
    $('.invClose').checked = S.invalidateOnClose;
    $('.maxAge').value = S.maxAgeBars;
  }

  function renderBadge() {
    const hhmm = state.lastRun ? state.lastRun.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--';
    const extras = TIMEFRAMES.filter((t) => S.tfs[t.label]).length;
    const tfs = state.chartTfs.join(', ') + (extras ? ` +${extras}` : '');
    dot.style.background = !S.enabled ? '#bbb' : state.error ? '#F44336' : '#4CAF50';
    label.textContent = S.enabled ? `CRT${tfs ? ` (${tfs})` : ''} · ${state.lastCount} · ${hhmm}` : `CRT · ${T.off}`;
    const toggle = $('.toggle');
    toggle.textContent = S.enabled ? T.off : T.on;
    toggle.title = S.enabled ? T.disable : T.enable;
    badge.title = state.error ? `${T.error}: ${state.error}` : T.tooltip;
  }

  // Panel events
  grid.addEventListener('change', (e) => { const tf = e.target.dataset.tf; if (tf) { S.tfs[tf] = e.target.checked; applyChange(); } });
  const applyRange = () => {
    const idx = (v) => TIMEFRAMES.findIndex((t) => t.label === v);
    let a = idx($('.from').value), b = idx($('.to').value);
    if (a > b) [a, b] = [b, a];
    TIMEFRAMES.forEach((t, i) => { S.tfs[t.label] = i >= a && i <= b; });
    applyChange();
  };
  $('.from').addEventListener('change', applyRange);
  $('.to').addEventListener('change', applyRange);
  $('.noneBtn').addEventListener('click', () => { TIMEFRAMES.forEach((t) => { S.tfs[t.label] = false; }); applyChange(); });
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
