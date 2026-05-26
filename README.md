# ROCKNIX Control

A [Decky Loader](https://decky.xyz) plugin for CPU, GPU, and fan control on ROCKNIX devices.

## Features

- **CPU frequency control** — Per-cluster max frequency (Little/Mid/Big)
- **GPU frequency control** — Max frequency limit
- **Fan curve editor** — Custom multi-point temperature-to-PWM curves
- **Preset system** — Save/load hardware profiles
- **Per-game profiles** — Automatically apply presets when games launch
- **Real-time monitoring** — Live CPU/GPU temps and actual frequencies

## Requirements

- ROCKNIX with Steam and [Decky Loader](https://decky.xyz/) installed
  ```bash
  curl -L https://decky.seilent.net | sh
  ```
  <details><summary>Alternative URL</summary>

  ```bash
  curl -L https://gist.github.com/seilent/5528d25197518a6b3851d8d3010ab881/raw/f0541c0b1cf9961fd696c9c496dab8132d8b3f61/install_release.sh | sh
  ```
  </details>

## Installation

1. Enable Developer Mode in Decky settings
2. Download `rocknix-control.zip` from [Releases](https://github.com/seilent/rocknix-control/releases)
3. Install plugin from zip file via Decky

## Building

```bash
pnpm install
pnpm build
```

## License

MIT
