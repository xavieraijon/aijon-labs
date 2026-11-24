<p align="center">
  <img src="icon.svg" width="72" height="72" alt="Tradesea CRT">
</p>

<h1 align="center">Tradesea CRT</h1>

<p align="center">
  <strong>Candle Range Theory on your Tradesea charts, on any timeframe from 15 minutes to monthly, updated live.</strong><br>
  A free userscript by <a href="https://github.com/xavieraijon/aijon-labs">AijonLabs</a>.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-1.5.0-2962FF">
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

Tradesea does not let you add custom indicators. **Tradesea CRT** adds the one many CRT traders miss: it scans the timeframes you choose, from **15 minutes to monthly**, finds valid Candle Range Theory setups and draws their range as **Horizontal Rays** directly on your charts, keeping them up to date as candles close.

## Features

- **Any timeframe from 15m to M**: 15m, 30m, 1H, 2H, 3H, 4H, 6H, 8H, 12H, D, W and M. Pick a range (*from 15m to D*) or tick them one by one. Candles are aligned to the CME session exactly as Tradesea draws them.
- **Active timeframe mode**: follows whatever timeframe the chart is on, including ones outside the list such as 5m or 45m.
- **Live**: recalculates every 30 seconds and instantly when you change symbol or timeframe.
- **Self-cleaning**: completed and invalidated setups disappear on their own.
- **Clear visuals**: one line colour per timeframe; label in green (bullish) or red (bearish); dashed while C2 is still open.
- **Two modes**: all selected timeframes, or only the chart's active timeframe.
- **Works on split layouts**: each chart gets the setups for its own symbol.
- **Lightweight UI**: a small draggable badge with a settings panel, in English or Spanish depending on your browser.
- **Private**: no external requests, no tracking, no orders. Everything runs inside your browser.

## Installation

1. Install a userscript manager:
   [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Edge, Firefox, Safari) or [Violentmonkey](https://violentmonkey.github.io/) (Chrome, Edge, Firefox).
2. **Chrome / Edge only**: open the extension's details page (`chrome://extensions` → Tampermonkey → *Details*) and turn on **Allow User Scripts**. On older versions, enable *Developer mode* instead. Without this step the script will not run.
3. Click **[Install](https://raw.githubusercontent.com/xavieraijon/aijon-labs/main/userscripts/tradesea-crt/tradesea-crt.user.js)** and confirm in the userscript manager.
4. Open or reload [app.tradesea.ai](https://app.tradesea.ai/trade). The **CRT** badge appears at the bottom left of the chart.

Updates are automatic: your userscript manager checks this repository and installs new versions for you.

## How to use

### The badge

| Element | What it does |
|---|---|
| ● dot | Green = running · Amber = unsupported timeframe in *active* mode · Red = error (hover for details) · Grey = off |
| `CRT (all) · 4 · 09:15` | Mode, number of setups drawn, time of last update |
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

Timeframes outside the list (only in *active* mode, e.g. 5m or 45m) are drawn in blue-grey.

### Settings

| Setting | Default | Description |
|---|---|---|
| Timeframes | 15m to D | Scan the timeframes you tick (*From … to …* ticks a whole range at once), or only the chart's active one |
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

Intraday timeframes are built from 15-minute or 1-hour candles and aligned to the CME Globex session (18:00 New York); D and W are Tradesea's own trading-session candles, and M is built from them. They match Tradesea's candles one to one.

## Troubleshooting

| Problem | Solution |
|---|---|
| No badge appears | Check that *Allow User Scripts* / *Developer mode* is on (step 2) and that the script is enabled in the manager. Reload the page. |
| Red dot | Hover over the badge to read the error. If Tradesea changed its platform, update the script or [open an issue](https://github.com/xavieraijon/aijon-labs/issues). |
| Amber dot | You are in *active* mode on a timeframe the script cannot read (seconds, or multiples such as 2D). Switch timeframe or mode. |
| Too many rays | Untick timeframes, switch to *active* mode or lower *Max. age*. |
| Badge is off-screen | ⚙ → *Reset position*, or resize the window. |

## Limitations

- Seconds and multi-period timeframes (2D, 3W…) are not supported. Timeframes under 15m only work in *active* mode.
- Each timeframe looks back a limited history (about 10 trading days for 15m/30m, 6 weeks for hourly timeframes and 3 years for D/W/M), more than enough for the default *Max. age* of 30 bars.
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
