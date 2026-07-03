# ROCKNIX Control Enhanced

This fork extends the original ROCKNIX Control plugin with additional quality-of-life improvements, bug fixes, and per-game performance tuning features.

# Fan curve improvements

Preserves the 0°C / 0 PWM fan curve point when loading fancontrol.conf.
Prevents duplicate 0,0 entries from being added when saving fan curves multiple times.
Updated fan curve point numbering to start from Point 0, matching the underlying curve data.

# Game preset improvements

Fixed preset deletion cleanup so removing a preset also removes any associated entries from game_profiles.json, preventing stale or broken game profile mappings.
Added per-game CPU and GPU governor support, allowing governors to be stored and automatically applied alongside each game profile.

# Fan control startup fixes
Investigated custom fan profiles not being applied correctly after reboot.
Tracked the startup interaction between ROCKNIX Control and fancontrol.service.
Validated fan hwmon detection and custom fan curve initialization.

# CPU/GPU governor support

Added CPU governor selection to presets.
Added GPU governor selection to presets.

Governors are saved as part of each preset and automatically restored when the preset is applied.

Default preset governors are automatically restored after Steam startup.

Governors are restored correctly when switching between game presets and when exiting games.

# Live monitoring

Added live fan PWM percentage display.
Added live CPU temperature display.
Added live GPU temperature display.
Added live CPU governor monitoring (debug).
Added live GPU governor monitoring (debug).

# UI improvements

Moved the Delete Preset button out of Edit mode into the main preset menu for easier access.
Added a compact hardware status section displaying:
Fan PWM percentage
CPU temperature
GPU temperature
Added governor sliders for CPU and GPU preset configuration.
Backend improvements
Exposed current fan PWM percentage through get_current_settings().
Added backend support for applying saved CPU governors.
Added backend support for applying saved GPU governors.


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
