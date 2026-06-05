import os
import json
import glob
import asyncio
import subprocess
import decky

CPU_BASE = "/sys/devices/system/cpu/cpufreq/policy{}"
FAN_PLATFORM = "/sys/devices/platform/pwm-fan"
FAN_CONF = "/storage/.config/fancontrol.conf"

DEFAULT_FAN_CURVE = {"speeds": [51, 51, 153], "temps": [40000, 60000, 80000]}


def _discover_cpu_policies():
    policies = []
    cpufreq_dir = "/sys/devices/system/cpu/cpufreq"
    if os.path.isdir(cpufreq_dir):
        for entry in os.listdir(cpufreq_dir):
            if entry.startswith("policy"):
                try:
                    policies.append(int(entry.replace("policy", "")))
                except ValueError:
                    pass
    policies.sort()
    return policies


def _discover_gpu_devfreq():
    for entry in glob.glob("/sys/class/devfreq/*gpu*"):
        if os.path.exists(os.path.join(entry, "available_frequencies")):
            return entry
    for entry in glob.glob("/sys/class/devfreq/*"):
        if "gpu" in os.path.basename(entry).lower():
            return entry
    return None


CPU_POLICIES = _discover_cpu_policies()
GPU_BASE = _discover_gpu_devfreq()


def _find_fan_hwmon():
    pattern = os.path.join(FAN_PLATFORM, "hwmon", "hwmon*")
    for p in glob.glob(pattern):
        if os.path.exists(os.path.join(p, "pwm1")):
            return p
    return None


def _read(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception as e:
        decky.logger.error(f"Read failed {path}: {e}")
        return None


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except Exception as e:
        decky.logger.error(f"Write failed {value} to {path}: {e}")
        return False


async def _aread(path):
    return await asyncio.to_thread(_read, path)


async def _awrite(path, value):
    return await asyncio.to_thread(_write, path, value)


_presets_cache = None
_game_profiles_cache = None


def _presets_path():
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "presets.json")


def _build_default_preset():
    preset = {}
    for policy in CPU_POLICIES:
        base = CPU_BASE.format(policy)
        preset[f"cpu_policy{policy}_max"] = int(_read(os.path.join(base, "scaling_max_freq")) or 0)
        preset[f"cpu_policy{policy}_min"] = int(_read(os.path.join(base, "scaling_min_freq")) or 0)
    if GPU_BASE:
        preset["gpu_max"] = int(_read(os.path.join(GPU_BASE, "max_freq")) or 0)
        preset["gpu_min"] = int(_read(os.path.join(GPU_BASE, "min_freq")) or 0)
    preset["fan_mode"] = "auto"
    preset["fan_pwm"] = 0
    return preset


DEFAULT_PRESET = _build_default_preset()


def _load_presets():
    global _presets_cache
    if _presets_cache is not None:
        return _presets_cache
    path = _presets_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            data = {"presets": {}}
    else:
        data = {"presets": {}}
    if "Default" not in data["presets"]:
        data["presets"]["Default"] = DEFAULT_PRESET
        _save_presets(data)
    _presets_cache = data
    return data


def _save_presets(data):
    global _presets_cache
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(_presets_path(), "w") as f:
        json.dump(data, f, indent=2)
    _presets_cache = data


def _game_profiles_path():
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "game_profiles.json")


def _load_game_profiles():
    global _game_profiles_cache
    if _game_profiles_cache is not None:
        return _game_profiles_cache
    path = _game_profiles_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                _game_profiles_cache = json.load(f)
                return _game_profiles_cache
        except Exception:
            pass
    _game_profiles_cache = {}
    return _game_profiles_cache


def _save_game_profiles(data):
    global _game_profiles_cache
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(_game_profiles_path(), "w") as f:
        json.dump(data, f, indent=2)
    _game_profiles_cache = data


def _parse_fan_conf():
    if not os.path.exists(FAN_CONF):
        return None
    content = _read(FAN_CONF)
    if not content:
        return None
    speeds = []
    temps = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("SPEEDS=("):
            vals = line.replace("SPEEDS=(", "").rstrip(")")
            speeds = [int(x) for x in vals.split()]
        elif line.startswith("TEMPS=("):
            vals = line.replace("TEMPS=(", "").rstrip(")")
            temps = [int(x) for x in vals.split()]
    if speeds and temps:
        pairs = list(dict.fromkeys(zip(temps, speeds)))
        pairs.sort()
        return {"speeds": [s for t, s in pairs], "temps": [t for t, s in pairs]}
    return None


def _write_fan_conf(speeds, temps):
    os.makedirs(os.path.dirname(FAN_CONF), exist_ok=True)
    pairs = sorted(zip(temps, speeds), reverse=True)
    desc_temps = [t for t, s in pairs]
    desc_speeds = [s for t, s in pairs]

    if 0 not in desc_temps:
        desc_temps.append(0)
        desc_speeds.append(0)

    content = f"SPEEDS=({' '.join(str(s) for s in desc_speeds)})\nTEMPS=({' '.join(str(t) for t in desc_temps)})\n"
    with open(FAN_CONF, "w") as f:
        f.write(content)


def _read_max_temp():
    max_temp = 0
    for zone in glob.glob("/sys/class/thermal/thermal_zone*/type"):
        zone_type = _read(zone)
        if zone_type and (zone_type.startswith("gpuss") or zone_type.startswith("cpuss")):
            temp_path = os.path.join(os.path.dirname(zone), "temp")
            val = _read(temp_path)
            if val:
                try:
                    max_temp = max(max_temp, int(val))
                except ValueError:
                    pass
    return max_temp


def _interpolate_pwm(temp, curve):
    temps = curve["temps"]
    speeds = curve["speeds"]
    if temp <= temps[0]:
        return speeds[0]
    if temp >= temps[-1]:
        return speeds[-1]
    for i in range(1, len(temps)):
        if temp <= temps[i]:
            t0, t1 = temps[i - 1], temps[i]
            s0, s1 = speeds[i - 1], speeds[i]
            if t1 == t0:
                return s1
            ratio = (temp - t0) / (t1 - t0)
            return int(s0 + ratio * (s1 - s0))
    return speeds[-1]


SYSTEM_CFG = "/storage/.config/system/configs/system.cfg"


def _get_system_setting(key, default=""):
    if not os.path.exists(SYSTEM_CFG):
        return default
    try:
        with open(SYSTEM_CFG, "r") as f:
            for line in f:
                if line.strip().startswith(key + "="):
                    return line.strip().split("=", 1)[1]
    except Exception:
        pass
    return default


def _set_system_setting(key, value):
    lines = []
    found = False
    if os.path.exists(SYSTEM_CFG):
        with open(SYSTEM_CFG, "r") as f:
            lines = f.readlines()
    with open(SYSTEM_CFG, "w") as f:
        for line in lines:
            if line.strip().startswith(key + "="):
                f.write(f"{key}={value}\n")
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f"{key}={value}\n")



async def _aload_presets():
    return await asyncio.to_thread(_load_presets)


async def _asave_presets(data):
    return await asyncio.to_thread(_save_presets, data)


async def _aload_game_profiles():
    return await asyncio.to_thread(_load_game_profiles)


async def _asave_game_profiles(data):
    return await asyncio.to_thread(_save_game_profiles, data)


async def _awrite_fan_conf(speeds, temps):
    return await asyncio.to_thread(_write_fan_conf, speeds, temps)


async def _aget_system_setting(key, default=""):
    return await asyncio.to_thread(_get_system_setting, key, default)


async def _aset_system_setting(key, value):
    return await asyncio.to_thread(_set_system_setting, key, value)


async def _aread_max_temp():
    return await asyncio.to_thread(_read_max_temp)


class Plugin:
    fan_hwmon = None
    _fan_curve = None
    _curve_task = None
    _apply_lock = None


    async def _fan_curve_loop(self):
        decky.logger.info("Fan curve loop started")
        last_pwm = -1
        try:
            while True:
                if not self._fan_curve or not self.fan_hwmon:
                    await asyncio.sleep(2)
                    continue
                temp = await _aread_max_temp()
                pwm = _interpolate_pwm(temp, self._fan_curve)
                pwm = max(0, min(255, pwm))
                if pwm != last_pwm:
                    await _awrite(os.path.join(self.fan_hwmon, "pwm1_enable"), 1)
                    await _awrite(os.path.join(self.fan_hwmon, "pwm1"), pwm)
                    decky.logger.info(f"Fan curve: temp={temp} -> pwm={pwm}")
                    last_pwm = pwm
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            decky.logger.info("Fan curve loop cancelled")

    def _start_curve_loop(self):
        if self._curve_task is None or self._curve_task.done():
            self._curve_task = asyncio.get_event_loop().create_task(self._fan_curve_loop())
            decky.logger.info("Fan curve loop task created")

    async def _stop_curve_loop(self):
        if self._curve_task and not self._curve_task.done():
            self._curve_task.cancel()
            decky.logger.info("Fan curve loop task stopped")
        self._curve_task = None
        self._fan_curve = None
        if self.fan_hwmon:
            await _awrite(os.path.join(self.fan_hwmon, "pwm1_enable"), 2)


    async def get_cpu_info(self):
        result = {}
        for policy in CPU_POLICIES:
            base = CPU_BASE.format(policy)
            freqs_raw = await _aread(os.path.join(base, "scaling_available_frequencies"))
            result[str(policy)] = {
                "available_frequencies": [int(x) for x in freqs_raw.split()] if freqs_raw else [],
                "governor": await _aread(os.path.join(base, "scaling_governor")),
                "min_freq": int(await _aread(os.path.join(base, "scaling_min_freq")) or 0),
                "max_freq": int(await _aread(os.path.join(base, "scaling_max_freq")) or 0),
            }
        return result

    async def set_cpu_max_freq(self, policy: int, freq: int):
        return await _awrite(os.path.join(CPU_BASE.format(policy), "scaling_max_freq"), freq)

    async def set_cpu_min_freq(self, policy: int, freq: int):
        return await _awrite(os.path.join(CPU_BASE.format(policy), "scaling_min_freq"), freq)

    async def set_cpu_governor(self, policy: int, governor: str):
        return await _awrite(os.path.join(CPU_BASE.format(policy), "scaling_governor"), governor)


    async def get_gpu_info(self):
        if not GPU_BASE:
            return {"error": "GPU devfreq not found", "available_frequencies": [], "governor": None, "min_freq": 0, "max_freq": 0}
        freqs_raw = await _aread(os.path.join(GPU_BASE, "available_frequencies"))
        return {
            "available_frequencies": [int(x) for x in freqs_raw.split()] if freqs_raw else [],
            "governor": await _aread(os.path.join(GPU_BASE, "governor")),
            "min_freq": int(await _aread(os.path.join(GPU_BASE, "min_freq")) or 0),
            "max_freq": int(await _aread(os.path.join(GPU_BASE, "max_freq")) or 0),
        }

    async def set_gpu_max_freq(self, freq: int):
        if not GPU_BASE:
            return False
        decky.logger.info(f"set_gpu_max_freq called with: {freq} (type: {type(freq).__name__})")
        result = await _awrite(os.path.join(GPU_BASE, "max_freq"), int(freq))
        decky.logger.info(f"set_gpu_max_freq result: {result}")
        return result

    async def set_gpu_min_freq(self, freq: int):
        if not GPU_BASE:
            return False
        return await _awrite(os.path.join(GPU_BASE, "min_freq"), freq)

    async def set_gpu_governor(self, governor: str):
        if not GPU_BASE:
            return False
        return await _awrite(os.path.join(GPU_BASE, "governor"), governor)


    async def get_temps(self):
        cpu_temp = 0
        gpu_temp = 0
        for zone in glob.glob("/sys/class/thermal/thermal_zone*/type"):
            zone_type = await _aread(zone)
            if not zone_type:
                continue
            temp_path = os.path.join(os.path.dirname(zone), "temp")
            val = await _aread(temp_path)
            if not val:
                continue
            try:
                t = int(val)
            except ValueError:
                continue
            if zone_type.startswith("cpuss"):
                cpu_temp = max(cpu_temp, t)
            elif zone_type.startswith("gpuss"):
                gpu_temp = max(gpu_temp, t)
        return {"cpu": cpu_temp, "gpu": gpu_temp}


    async def get_fan_info(self):
        if not self.fan_hwmon:
            return {"error": "Fan hwmon not found"}
        return {
            "pwm": int(await _aread(os.path.join(self.fan_hwmon, "pwm1")) or 0),
            "rpm": int(await _aread(os.path.join(self.fan_hwmon, "fan1_input")) or 0),
            "enable": int(await _aread(os.path.join(self.fan_hwmon, "pwm1_enable")) or 0),
            "curve_active": self._curve_task is not None and not self._curve_task.done(),
        }

    async def set_fan_speed(self, pwm: int):
        if not self.fan_hwmon:
            return False
        pwm = max(0, min(255, pwm))
        await _awrite(os.path.join(self.fan_hwmon, "pwm1_enable"), 1)
        return await _awrite(os.path.join(self.fan_hwmon, "pwm1"), pwm)

    async def set_fan_auto(self):
        if not self.fan_hwmon:
            return False
        return await _awrite(os.path.join(self.fan_hwmon, "pwm1_enable"), 2)


    async def get_fan_curve(self):
        profile = await _aget_system_setting("cooling.profile", "moderate")
        if profile == "custom":
            curve = _parse_fan_conf()
            if curve:
                return {**curve, "profile": "custom"}
        return {"speeds": DEFAULT_FAN_CURVE["speeds"][:], "temps": DEFAULT_FAN_CURVE["temps"][:], "profile": profile}

    async def set_fan_curve(self, speeds: str, temps: str):
        speeds_list = json.loads(speeds)
        temps_list = json.loads(temps)
        if len(speeds_list) != len(temps_list):
            return False
        for i in range(1, len(speeds_list)):
            if speeds_list[i] < speeds_list[i - 1]:
                return False
        for i in range(1, len(temps_list)):
            if temps_list[i] <= temps_list[i - 1]:
                return False
        await _awrite_fan_conf(speeds_list, temps_list)
        await _aset_system_setting("cooling.profile", "custom")
        self._fan_curve = {"speeds": speeds_list, "temps": temps_list}
        self._start_curve_loop()
        return True

    async def set_fan_profile(self, profile: str):
        await _aset_system_setting("cooling.profile", profile)
        if profile == "custom":
            curve = _parse_fan_conf()
            if curve:
                self._fan_curve = curve
                self._start_curve_loop()
        else:
            await self._stop_curve_loop()
        return True


    async def get_default_preset(self):
        preset = {}
        for policy in CPU_POLICIES:
            base = CPU_BASE.format(policy)
            preset[f"cpu_policy{policy}_max"] = int(await _aread(os.path.join(base, "scaling_max_freq")) or 0)
            preset[f"cpu_policy{policy}_min"] = int(await _aread(os.path.join(base, "scaling_min_freq")) or 0)
        if GPU_BASE:
            preset["gpu_max"] = int(await _aread(os.path.join(GPU_BASE, "max_freq")) or 0)
            preset["gpu_min"] = int(await _aread(os.path.join(GPU_BASE, "min_freq")) or 0)
        preset["fan_mode"] = "auto"
        preset["fan_curve"] = {
            "speeds": [51, 51, 153],
            "temps": [40000, 60000, 80000]
        }
        return preset


    async def get_presets(self):
        data = await _aload_presets()
        return list(data["presets"].keys())

    async def get_preset(self, name: str):
        data = await _aload_presets()
        return data["presets"].get(name)

    async def save_preset(self, name: str, settings: str):
        data = await _aload_presets()
        data["presets"][name] = json.loads(settings)
        await _asave_presets(data)
        return True

    async def rename_preset(self, old_name: str, new_name: str):
        data = await _aload_presets()
        if old_name in data["presets"] and new_name != old_name:
            data["presets"][new_name] = data["presets"].pop(old_name)
            await _asave_presets(data)
            return True
        return False

    async def delete_preset(self, name: str):
        if name == "Default":
            return False

        data = await _aload_presets()
        if name in data["presets"]:
            del data["presets"][name]
            await _asave_presets(data)

            profiles = await _aload_game_profiles()
            profiles = {
                game_id: preset_name
                for game_id, preset_name in profiles.items()
                if preset_name != name
            }
            await _asave_game_profiles(profiles)

            return True

        return False

    async def apply_preset(self, name: str):
        if not self._apply_lock:
            self._apply_lock = asyncio.Lock()
        async with self._apply_lock:
            decky.logger.info(f"apply_preset called with: {name}")
            data = await _aload_presets()
            preset = data["presets"].get(name)
            if not preset:
                decky.logger.info(f"apply_preset: preset '{name}' not found. Available: {list(data['presets'].keys())}")
                return False
            for policy in CPU_POLICIES:
                max_key = f"cpu_policy{policy}_max"
                min_key = f"cpu_policy{policy}_min"
                if max_key in preset:
                    await self.set_cpu_max_freq(policy, preset[max_key])
                if min_key in preset:
                    await self.set_cpu_min_freq(policy, preset[min_key])
            if "gpu_max" in preset:
                await self.set_gpu_max_freq(preset["gpu_max"])
            if "gpu_min" in preset:
                await self.set_gpu_min_freq(preset["gpu_min"])
            if "fan_mode" in preset:
                if preset["fan_mode"] == "auto":
                    await self._stop_curve_loop()
                    await self.set_fan_auto()
                elif preset["fan_mode"] == "manual" and preset.get("fan_pwm") is not None:
                    await self._stop_curve_loop()
                    await self.set_fan_speed(preset["fan_pwm"])
            if "fan_curve" in preset:
                curve = preset["fan_curve"]
                self._fan_curve = {"speeds": curve["speeds"], "temps": curve["temps"]}
                await _awrite_fan_conf(curve["speeds"], curve["temps"])
                await _aset_system_setting("cooling.profile", "custom")
                self._start_curve_loop()
            return True

    async def get_current_settings(self):
        settings = {}
        for policy in CPU_POLICIES:
            base = CPU_BASE.format(policy)
            settings[f"cpu_policy{policy}_max"] = int(await _aread(os.path.join(base, "scaling_max_freq")) or 0)
            settings[f"cpu_policy{policy}_min"] = int(await _aread(os.path.join(base, "scaling_min_freq")) or 0)
        settings["gpu_max"] = int(await _aread(os.path.join(GPU_BASE, "max_freq")) or 0) if GPU_BASE else 0
        settings["gpu_min"] = int(await _aread(os.path.join(GPU_BASE, "min_freq")) or 0) if GPU_BASE else 0
        if self.fan_hwmon:
            enable = int(await _aread(os.path.join(self.fan_hwmon, "pwm1_enable")) or 0)
            if self._curve_task and not self._curve_task.done():
                settings["fan_mode"] = "curve"
            elif enable == 2:
                settings["fan_mode"] = "auto"
            else:
                settings["fan_mode"] = "manual"
            settings["fan_pwm"] = int(await _aread(os.path.join(self.fan_hwmon, "pwm1")) or 0)
        curve = _parse_fan_conf()
        settings["fan_curve"] = curve if curve else DEFAULT_FAN_CURVE
        return settings


    async def get_game_profile(self, game_id: str):
        data = await _aload_game_profiles()
        result = data.get(game_id)
        decky.logger.info(f"get_game_profile({game_id}) = {result}")
        return result

    async def set_game_profile(self, game_id: str, preset_name: str):
        decky.logger.info(f"set_game_profile({game_id}, {preset_name})")
        data = await _aload_game_profiles()
        data[game_id] = preset_name
        await _asave_game_profiles(data)
        return True

    async def delete_game_profile(self, game_id: str):
        data = await _aload_game_profiles()
        data.pop(game_id, None)
        await _asave_game_profiles(data)
        return True

    async def get_all_game_profiles(self):
        return await _aload_game_profiles()


    async def _main(self):
        self.fan_hwmon = _find_fan_hwmon()
        decky.logger.info(f"ROCKNIX Control loaded. Fan hwmon: {self.fan_hwmon}")
        decky.logger.info(f"Discovered CPU policies: {CPU_POLICIES}")
        decky.logger.info(f"Discovered GPU devfreq: {GPU_BASE}")
        subprocess.run(["systemctl", "stop", "fancontrol"], capture_output=True, timeout=10)
        decky.logger.info("fancontrol service stopped")
        profile = await _aget_system_setting("cooling.profile", "moderate")
        if profile == "custom":
            curve = _parse_fan_conf()
            if curve:
                self._fan_curve = curve
                self._start_curve_loop()

    async def _unload(self):
        await self._stop_curve_loop()
        if self.fan_hwmon:
            await _awrite(os.path.join(self.fan_hwmon, "pwm1_enable"), 2)
        subprocess.run(["systemctl", "start", "fancontrol"], capture_output=True, timeout=10)
        decky.logger.info("ROCKNIX Control unloaded.")
