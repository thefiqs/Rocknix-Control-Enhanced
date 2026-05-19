# ROCKNIX Control

A [Decky Loader](https://decky.xyz) plugin for CPU, GPU, and fan control on ROCKNIX devices.

## Features

- **CPU frequency control** — Per-cluster max frequency (Little/Mid/Big)
- **GPU frequency control** — Max frequency limit
- **Fan curve editor** — Custom multi-point temperature-to-PWM curves
- **Preset system** — Save/load hardware profiles
- **Per-game profiles** — Automatically apply presets when games launch
- **Real-time monitoring** — Live CPU/GPU temps and actual frequencies

## Installation

1. Install [Decky Loader](https://decky.xyz) on your ROCKNIX device
2. Enable Developer Mode in Decky settings
3. Download `rocknix-control.zip` from [Releases](https://github.com/seilent/rocknix-control/releases)
4. Install plugin from zip file via Decky

## Building

```bash
pnpm install
pnpm build
```

## License

MIT
