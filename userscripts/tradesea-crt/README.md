<p align="center">
  <img src="icon.svg" width="72" height="72" alt="Tradesea CRT">
</p>

<h1 align="center">Tradesea CRT</h1>

<p align="center">
  <strong>Candle Range Theory on your Tradesea charts, on whatever timeframe you are looking at (2D, 10H, 33D…), updated live.</strong><br>
  A free userscript by <a href="https://github.com/xavieraijon/aijon-labs">AijonLabs</a>.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-1.6.0-2962FF">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-089981">
  <img alt="Tampermonkey" src="https://img.shields.io/badge/Tampermonkey-supported-00485B">
  <img alt="Violentmonkey" src="https://img.shields.io/badge/Violentmonkey-supported-1E88E5">
</p>

<p align="center">
  <a href="https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js"><strong>⬇ Install</strong></a>
  &nbsp;·&nbsp; <a href="README.es.md">Leer en español</a>
  &nbsp;·&nbsp; <a href="../../CHANGELOG.md#tradesea-crt">Changelog</a>
</p>

---

Tradesea does not let you add custom indicators. **Tradesea CRT** adds the one many CRT traders miss: it reads the candles of each chart, **whatever timeframe it is set to**, finds valid Candle Range Theory setups and draws their range as **Horizontal Rays** directly on the chart, keeping them up to date as candles close. There is nothing to choose: change the timeframe and the ranges change with it.

## Features

- **Always the chart's timeframe**: 15m, 4H, 10H, D, 2D, 33D, 2W, 3M, even seconds. Nothing to select: switch timeframe and the setups follow. In a split layout each chart uses its own timeframe and symbol.
- **Extra timeframes, if you want them**: add the ranges of 15m to M on top of the chart's own (for example 4H and D ranges while you look at 15m), with a *From … to …* selector. None by default.
- **Live**: recalculates every 15 seconds and instantly when you change symbol or timeframe.
- **Self-cleaning**: completed and invalidated setups disappear on their own.
- **Clear visuals**: one line colour per timeframe; label in green (bullish) or red (bearish); dashed while C2 is still open.
- **Lightweight UI**: a small draggable badge with a settings panel, in English or Spanish depending on your browser.
- **Private**: no external requests, no tracking, no orders. Everything runs inside your browser.

## Installation

1. Install a userscript manager:
   [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Edge, Firefox, Safari) or [Violentmonkey](https://violentmonkey.github.io/) (Chrome, Edge, Firefox).
2. **Allow user scripts** (Chrome, Brave, Edge, Opera, Vivaldi). Without this step the script does not run.
   1. Open Tampermonkey's details page: right-click the Tampermonkey icon → **Manage extension**, or paste this address into a new tab:
      - Chrome, Brave, Vivaldi: `chrome://extensions/?id=dhdgffkkebhmkfjojejmpbldmpobfkfo`
      - Edge: `edge://extensions/?id=iikmkjmpaadaobahmlepeloendndfphd`
   2. Turn on the switch whose name depends on your browser's language (see [the table below](#name-of-the-switch-in-each-language)). In English it is **Allow User Scripts**.
   3. The browser warns that the extension can run code it has not reviewed. That is expected for any userscript manager.

   Browsers based on Chromium older than 138 (Chrome 138 came out in mid-2025) have no such switch: turn on **Developer mode** at the top right of the extensions page instead.

   Firefox and Safari do not need this step.
3. Click **[Install](https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js)** and confirm in the userscript manager.
4. Open or reload [app.tradesea.ai](https://app.tradesea.ai/trade). The **CRT** badge appears at the bottom left of the chart.

Updates are automatic: your userscript manager checks this repository and installs new versions for you.

#### Name of the switch in each language

Taken from Chromium's own translations, which Chrome, Brave and Vivaldi use as they are. Edge and Opera translate parts of their interface separately, so their wording may differ slightly.

| Language | Switch on Tampermonkey's details page (138+) | Before 138: on the extensions page |
|---|---|---|
| English (US) | Allow User Scripts | Developer mode |
| English (UK) | Allow user scripts | Developer mode |
| Español (España y Latinoamérica) | Permitir secuencias de comandos del usuario | Modo Desarrollador (España) · Modo de desarrollador (Latinoamérica) |
| Català | Permet els scripts d'usuari | Mode de desenvolupador |
| Français | Autoriser les scripts utilisateur | Mode développeur |
| Deutsch | Nutzerscripts zulassen | Entwicklermodus |
| Italiano | Consenti script utente | Modalità sviluppatore |
| Português (Brasil) | Permitir scripts de usuário | Modo do desenvolvedor |
| Português (Portugal) | Permitir scripts do utilizador | Modo de programador |

## How to use

### The badge

| Element | What it does |
|---|---|
| ● dot | Green = running · Red = error (hover for details) · Grey = off |
| `CRT (2D +2) · 4 · 09:15` | The charts' timeframes (+ number of extra timeframes), setups drawn, time of last update |
| ↻ | Recalculate now (also restores rays you deleted by mistake) |
| ⚙ | Open settings |
| `off` / `on` | Turn the script off (removes its rays) or back on |

Drag the badge by its text to place it anywhere. The position is remembered.

### Reading the rays

Each setup draws two rays starting at the C1 candle: its **High** and its **Low**.

```
2H High (Bearish)      ← label colour: green = Bullish, red = Bearish
2H Low (Bearish)       ← line colour: timeframe · solid = C2 closed · dashed = C2 still forming
```

| Timeframe | 15m | 30m | 1H | 2H | 3H | 4H | 6H | 8H | 12H | D | W | M |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Line colour | cyan | light green | grey | blue | purple | orange | brown | teal | pink | indigo | slate | black |

The chart's own timeframe uses the colour of the list when it is in it, and indigo-blue otherwise (2D, 10H, 33D…).

### Settings

| Setting | Default | Description |
|---|---|---|
| Chart's timeframe | Always | The setups of each chart's own timeframe are always drawn, whatever it is |
| Extra timeframes | None | Ranges of other timeframes (15m to M) drawn on top; *From … to …* ticks a whole range at once, *None* clears them |
| Active (C2 closed) | On | Setups whose C2 has closed and whose target has not been reached |
| Forming (C2 still open) | On | Setups where the current candle is sweeping C1 (may still fail) |
| 50% level | Off | Adds a dotted ray at the middle of C1, the usual first target |
| Invalidate when a candle closes outside the range | On | Removes a setup once a later candle closes beyond C1 on the swept side |
| Max. age | 30 bars | Ignores setups whose C2 is older than this, per timeframe |

Settings are stored in your browser and survive reloads.

## Detection rules

For every pair of consecutive candles, **C1** (range) and **C2**:

1. **Setup**: C2 trades beyond **exactly one** extreme of C1 (a liquidity sweep) and closes back **inside** C1's range.
   Sweep of the low → **Bullish** (target: C1 High). Sweep of the high → **Bearish** (target: C1 Low).
2. **Completed**: price reaches the opposite extreme of C1. The setup is removed.
3. **Invalidated**: the setup is removed if
   - price trades beyond C2's sweep wick, or
   - *(optional, on by default)* a later candle **closes** outside C1 on the swept side.
4. Candles that sweep both extremes, or neither, are ignored.

The chart's timeframe uses the very candles the chart draws, so they always match. Extra timeframes are built from the data feed: intraday ones from 15-minute or 1-hour candles aligned to the CME Globex session (18:00 New York), D and W from Tradesea's own trading-session candles, and M from the daily ones.

## Troubleshooting

| Problem | Solution |
|---|---|
| No badge appears | Check that the user scripts switch (or *Developer mode* before version 138) is on, with the [name for your language](#name-of-the-switch-in-each-language) (step 2), and that the script is enabled in the manager. Reload the page. |
| Red dot | Hover over the badge to read the error. If Tradesea changed its platform, update the script or [open an issue](https://github.com/xavieraijon/aijon-labs/issues). |
| Too many rays | Remove the extra timeframes (⚙ → *None*) or lower *Max. age*. |
| Badge is off-screen | ⚙ → *Reset position*, or resize the window. |

## Limitations

- On tick, range or other non-time charts, the latest candle is always treated as still forming.
- The chart's timeframe looks back as far as the candles the chart has loaded. Extra timeframes look back about 10 trading days (15m/30m), 6 weeks (hourly) and 3 years (D/W/M), more than enough for the default *Max. age* of 30 bars.
- Tradesea has no public API for add-ons. The script uses the chart's internal interface, so a platform update can break it until a new version is released.
- Rays are regular chart drawings. If you save your layout, Tradesea may keep a snapshot of them; the script cleans and redraws its own rays on load.

## Privacy and security

- **No network requests** of its own. Candles come from the data feed Tradesea already uses for your chart.
- **Read-only** with respect to your account: it never places, modifies or cancels orders.
- No analytics, no tracking, no remote code. The full source is this single file. Read it before installing.

## Disclaimer

This is an independent, free and open-source tool. It is **not affiliated with, endorsed by or supported by Tradesea or TradingView**. All trademarks belong to their owners.

It is provided **for educational and analytical purposes only** and is **not financial advice**. Futures trading involves substantial risk of loss and is not suitable for every investor. You are solely responsible for your trading decisions. Make sure your use of userscripts complies with the terms of the platforms and prop firms you use.

## License

[MIT](../../LICENSE) © Xavi Aijon · AijonLabs
