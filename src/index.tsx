import { callable, definePlugin } from "@decky/api";
import {
  PanelSection, PanelSectionRow, SliderField,
  DropdownItem, ButtonItem, TextField
} from "@decky/ui";
import { useState, useEffect, useRef, FC } from "react";
import { FaCog, FaPlus, FaPen, FaTrash } from "react-icons/fa";


declare const SteamClient: {
  GameSessions: {
    RegisterForAppLifetimeNotifications: (cb: (e: {unAppID: number, bRunning: boolean}) => void) => {unregister: () => void};
  };
};

declare const appStore: {
  GetAppOverviewByAppID: (appId: number) => { display_name: string } | null;
};

interface CpuPolicyInfo {
  available_frequencies: number[];
  governor: string;
  max_freq: number;
  min_freq: number;
}
type CpuInfo = { [key: string]: CpuPolicyInfo };

interface GpuInfo {
  available_frequencies: number[];
  governor: string;
  max_freq: number;
  min_freq: number;
}

interface FanCurve { speeds: number[]; temps: number[]; profile: string; }

interface Preset {
  [key: string]: number | string | undefined | { speeds: number[]; temps: number[] };
  gpu_max: number;
  gpu_min: number;

  fan_mode: string;
  fan_pwm: number;
  fan_pwm_percent?: number;
}

interface CurvePoint { temp: number; speed: number; }


const getCpuInfo = callable<[], CpuInfo>("get_cpu_info");
const getGpuInfo = callable<[], GpuInfo>("get_gpu_info");
const getTemps = callable<[], { cpu: number; gpu: number }>("get_temps");
const setCpuMaxFreq = callable<[policy: number, freq: number], boolean>("set_cpu_max_freq");
const setGpuMaxFreq = callable<[freq: number], boolean>("set_gpu_max_freq");
const getPresets = callable<[], string[]>("get_presets");
const getPreset = callable<[name: string], Preset | null>("get_preset");
const savePreset = callable<[name: string, settings: string], boolean>("save_preset");
const renamePreset = callable<[oldName: string, newName: string], boolean>("rename_preset");
const deletePreset = callable<[name: string], boolean>("delete_preset");
const applyPreset = callable<[name: string], boolean>("apply_preset");
const getCurrentSettings = callable<[], Preset>("get_current_settings");
const getFanCurve = callable<[], FanCurve>("get_fan_curve");
const saveFanCurve = callable<[speeds: string, temps: string], boolean>("set_fan_curve");
const setFanProfile = callable<[profile: string], boolean>("set_fan_profile");
const getGameProfile = callable<[gameId: string], string | null>("get_game_profile");
const setGameProfile = callable<[gameId: string, presetName: string], boolean>("set_game_profile");


const state = {
  runningAppId: 0,
  runningGameName: "",
  activePreset: "Default",  // what's actually applied to hardware
};

let switching = false;


function getPolicyLabels(cpuInfo: CpuInfo): { [key: string]: string } {
  const policies = Object.keys(cpuInfo).sort((a, b) => Number(a) - Number(b));
  if (policies.length === 1) return { [policies[0]]: "CPU" };
  const sorted = [...policies].sort((a, b) => {
    const maxA = cpuInfo[a]?.available_frequencies?.slice(-1)[0] ?? 0;
    const maxB = cpuInfo[b]?.available_frequencies?.slice(-1)[0] ?? 0;
    return maxA - maxB;
  });
  const labels: { [key: string]: string } = {};
  sorted.forEach((p, i) => {
    if (sorted.length === 2) {
      labels[p] = i === 0 ? "Little" : "Big";
    } else if (sorted.length === 3) {
      labels[p] = i === 0 ? "Little" : i === 1 ? "Mid" : "Big";
    } else {
      labels[p] = `Cluster ${p}`;
    }
  });
  return labels;
}

const DEFAULT_FAN_CURVE: CurvePoint[] = [
  { temp: 40000, speed: 51 },
  { temp: 60000, speed: 51 },
  { temp: 80000, speed: 153 },
];


const FanCurveEditor: FC<{
  points: CurvePoint[];
  onChange: (points: CurvePoint[]) => void;
  disabled: boolean;
}> = ({ points, onChange, disabled }) => {

  const updateTemp = (index: number, temp: number) => {
    const updated = [...points];
    updated[index] = { ...updated[index], temp };
    updated.sort((a, b) => a.temp - b.temp);
    onChange(enforceMonotonic(updated));
  };

  const updateSpeed = (index: number, speed: number) => {
    const updated = [...points];
    updated[index] = { ...updated[index], speed };
    onChange(enforceMonotonic(updated));
  };

  const addPoint = () => {
    const last = points[points.length - 1];
    const secondLast = points.length >= 2 ? points[points.length - 2] : last;
    const newTemp = Math.min(Math.round((secondLast.temp + last.temp) / 2) + 5000, 100000);
    const newSpeed = Math.min(Math.round((secondLast.speed + last.speed) / 2), 255);
    const updated = [...points, { temp: newTemp, speed: newSpeed }];
    updated.sort((a, b) => a.temp - b.temp);
    onChange(enforceMonotonic(updated));
  };

  const removePoint = (index: number) => {
    if (points.length <= 2) return;
    onChange(points.filter((_, i) => i !== index));
  };

  return (
    <div>
      {points.map((pt, i) => (
        <div key={i}>
          <PanelSectionRow>
            <SliderField
              label={`Point ${i} - Temp`}
              description={`${pt.temp / 1000}°C`}
              value={pt.temp}
              min={30000} max={100000} step={1000}
              disabled={disabled}
              onChange={(val) => updateTemp(i, val)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <SliderField
              label={`Point ${i} - Speed`}
              description={`PWM ${pt.speed} (${Math.round(pt.speed / 255 * 100)}%)`}
              value={pt.speed}
              min={0} max={255} step={1}
              disabled={disabled}
              onChange={(val) => updateSpeed(i, val)}
            />
          </PanelSectionRow>
          {points.length > 2 && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={disabled} onClick={() => removePoint(i)}>
                <FaTrash /> Remove Point {i}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </div>
      ))}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={disabled} onClick={addPoint}>
          <FaPlus /> Add Point
        </ButtonItem>
      </PanelSectionRow>
    </div>
  );
};

function enforceMonotonic(points: CurvePoint[]): CurvePoint[] {
  const result = points.map((p) => ({ ...p }));
  for (let i = 1; i < result.length; i++) {
    if (result[i].speed < result[i - 1].speed) result[i].speed = result[i - 1].speed;
  }
  for (let i = result.length - 2; i >= 0; i--) {
    if (result[i].speed > result[i + 1].speed) result[i].speed = result[i + 1].speed;
  }
  return result;
}


function Content() {
  const [cpuInfo, setCpuInfo] = useState<CpuInfo | null>(null);
  const [gpuInfo, setGpuInfo] = useState<GpuInfo | null>(null);
  const [cpuMaxFreqs, setCpuMaxFreqs] = useState<{ [key: string]: number }>({});
  const [gpuMaxFreq, setGpuMaxFreqState] = useState<number>(0);
  const [liveCpuMax, setLiveCpuMax] = useState<{ [key: string]: number }>({});
  const [liveGpuMax, setLiveGpuMax] = useState<number>(0);
  const [temps, setTemps] = useState<{ cpu: number; gpu: number }>({ cpu: 0, gpu: 0 });

  const [presets, setPresetList] = useState<string[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>(state.activePreset);
  const [editMode, setEditMode] = useState<boolean>(false);
  const [editName, setEditName] = useState<string>("");
  const [fanPercent, setFanPercent] = useState<string>("--");

  const [curvePoints, setCurvePoints] = useState<CurvePoint[]>(DEFAULT_FAN_CURVE);

  const [runningAppId, setRunningAppId] = useState<number>(state.runningAppId);
  const [gameName, setGameName] = useState<string>(state.runningGameName);


  const refreshHardware = async () => {
    const [cpu, gpu, preset] = await Promise.all([getCpuInfo(), getGpuInfo(), getPreset(state.activePreset)]);
    setCpuInfo(cpu);
    setGpuInfo(gpu);
    const liveMax: { [key: string]: number } = {};
    for (const policy of Object.keys(cpu)) {
      liveMax[policy] = cpu[policy]?.max_freq ?? 0;
    }
    setLiveCpuMax(liveMax);
    setLiveGpuMax(gpu.max_freq);
    const presetMax: { [key: string]: number } = {};
    for (const policy of Object.keys(cpu)) {
      presetMax[policy] = (preset as any)?.[`cpu_policy${policy}_max`] ?? liveMax[policy];
    }
    setCpuMaxFreqs(presetMax);
    setGpuMaxFreqState((preset as any)?.gpu_max ?? gpu.max_freq);
  };

  const refreshPresets = async () => {
    const list = await getPresets();
    if (!list.includes("Default")) list.unshift("Default");
    setPresetList(list);
  };

  const refreshFanCurve = async () => {
    const curve = await getFanCurve();
    if (curve.speeds.length > 0 && curve.temps.length > 0) {
      const pts: CurvePoint[] = curve.temps.map((t, i) => ({
        temp: t, speed: curve.speeds[i] ?? 0,
      }));
      pts.sort((a, b) => a.temp - b.temp);
      setCurvePoints(pts);
    }
  };

  useEffect(() => {
    refreshHardware();
    refreshPresets();
    refreshFanCurve();
    const interval = setInterval(() => {
      if (switching) return;  // skip entire tick during profile switch to avoid RPC queue buildup
      if (state.runningAppId !== runningAppIdRef.current) setRunningAppId(state.runningAppId);
      if (state.runningGameName !== gameNameRef.current) setGameName(state.runningGameName);
      getTemps().then((t) => {
        setTemps((prev) => (prev.cpu === t.cpu && prev.gpu === t.gpu) ? prev : t);
      });
      getCpuInfo().then((cpu) => {
        const liveMax: { [key: string]: number } = {};
        for (const p of Object.keys(cpu)) liveMax[p] = cpu[p]?.max_freq ?? 0;
        setLiveCpuMax((prev) => {
          const keys = Object.keys(liveMax);
          if (keys.length === Object.keys(prev).length && keys.every((k) => prev[k] === liveMax[k])) return prev;
          return liveMax;
        });
      });
      getGpuInfo().then((gpu) => setLiveGpuMax((prev) => (prev === gpu.max_freq ? prev : gpu.max_freq)));
      
      getCurrentSettings().then((current) => {
        const value = current.fan_pwm_percent;
        setFanPercent(typeof value === "number" ? value.toFixed(1) : "--");
      });
      
      if (state.activePreset !== selectedPresetRef.current && !switching) {
        setSelectedPreset(state.activePreset);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const saveRef = useRef({ editMode, cpuMaxFreqs, gpuMaxFreq, editName, selectedPreset });
  saveRef.current = { editMode, cpuMaxFreqs, gpuMaxFreq, editName, selectedPreset };

  const selectedPresetRef = useRef(selectedPreset);
  selectedPresetRef.current = selectedPreset;

  const runningAppIdRef = useRef(runningAppId);
  runningAppIdRef.current = runningAppId;

  const gameNameRef = useRef(gameName);
  gameNameRef.current = gameName;

  useEffect(() => {
    return () => {
      const { editMode, cpuMaxFreqs, gpuMaxFreq, editName, selectedPreset } = saveRef.current;
      if (editMode) {
        getCurrentSettings().then((current) => {
          for (const policy of Object.keys(cpuMaxFreqs)) {
            (current as any)[`cpu_policy${policy}_max`] = cpuMaxFreqs[policy];
          }
          current.gpu_max = gpuMaxFreq;
          const name = editName.trim() || selectedPreset;
          savePreset(name, JSON.stringify(current)).then(() => applyPreset(name));
        });
      }
    };
  }, []);


  const handleSelectPreset = async (name: string) => {
    if (name === selectedPreset) return;
    switching = true;
    try {
      setSelectedPreset(name);
      state.activePreset = name;
      await applyPreset(name);
      await Promise.all([
        state.runningAppId > 0 ? setGameProfile(String(state.runningAppId), name) : Promise.resolve(),
        refreshHardware(),
        refreshFanCurve(),
      ]);
    } finally {
      switching = false;
    }
  };

  const handleCreatePreset = async () => {
    const name = `Preset ${presets.length}`;
    const settings = await getCurrentSettings();
    await savePreset(name, JSON.stringify(settings));
    await refreshPresets();
    setSelectedPreset(name);
    state.activePreset = name;
    setEditName(name);
    setEditMode(true);
  };

  const handleExitEditMode = async () => {
    const trimmed = editName.trim();
    if (trimmed && trimmed !== selectedPreset) {
      const ok = await renamePreset(selectedPreset, trimmed);
      if (ok) {
        setSelectedPreset(trimmed);
        state.activePreset = trimmed;
        await refreshPresets();
      }
    }
    const current = await getCurrentSettings();
    const name = trimmed || selectedPreset;
    for (const policy of Object.keys(cpuMaxFreqs)) {
      (current as any)[`cpu_policy${policy}_max`] = cpuMaxFreqs[policy];
    }
    current.gpu_max = gpuMaxFreq;
    await savePreset(name, JSON.stringify(current));
    await applyPreset(name);
    setEditMode(false);
  };

  const handleCancel = () => {
    setEditMode(false);
    refreshHardware();
    refreshFanCurve();
  };

  const handleDeletePreset = async () => {
    if (selectedPreset === "Default") return;
    await deletePreset(selectedPreset);
    setSelectedPreset("Default");
    state.activePreset = "Default";
    setEditMode(false);
    await refreshPresets();
  };


  const handleCpuMaxChange = async (policy: string, index: number) => {
    const freqs = cpuInfo?.[policy]?.available_frequencies;
    if (!freqs) return;
    const freq = freqs[index];
    setCpuMaxFreqs((prev) => ({ ...prev, [policy]: freq }));
  };

  const handleGpuMaxChange = async (index: number) => {
    const freqs = gpuInfo?.available_frequencies;
    if (!freqs) return;
    const freq = freqs[index];
    setGpuMaxFreqState(freq);
  };

  const handleCurveChange = async (points: CurvePoint[]) => {
    setCurvePoints(points);
    const sorted = [...points].sort((a, b) => a.temp - b.temp);
    await saveFanCurve(JSON.stringify(sorted.map(p => p.speed)), JSON.stringify(sorted.map(p => p.temp)));
    const current = await getCurrentSettings();
    await savePreset(selectedPreset, JSON.stringify(current));
  };


  if (!cpuInfo || !gpuInfo) {
    return (
      <PanelSection title="ROCKNIX Control">
        <PanelSectionRow><div>Loading...</div></PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <div>
      {runningAppId > 0 && (
        <PanelSection title={`Playing: ${gameName}`} />
      )}

      <PanelSection title={`Fan: ${fanPercent}%`} />
      
      <PanelSection title="Presets">
        <PanelSectionRow>
          <DropdownItem
            rgOptions={presets.map((p) => ({ data: p, label: p }))}
            selectedOption={selectedPreset}
            onChange={(opt) => handleSelectPreset(opt.data)}
          />
        </PanelSectionRow>
        {!editMode ? (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => { setEditName(selectedPreset); setEditMode(true); }}>
                <FaPen /> Edit
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleCreatePreset}>
                <FaPlus /> New Preset
              </ButtonItem>
            </PanelSectionRow>
            
            {selectedPreset !== "Default" && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={handleDeletePreset}>
                  Delete Preset
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        ) : (
          <>
            <PanelSectionRow>
              <TextField label="Rename Preset" value={editName} onChange={(e) => setEditName(e.target.value)} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleExitEditMode}>Save</ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleCancel}>Cancel</ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title={`CPU${temps.cpu ? ` (${(temps.cpu / 1000).toFixed(0)}°C)` : ""}`}>
        {Object.keys(cpuInfo).sort((a, b) => Number(a) - Number(b)).map((policy) => {
          const info = cpuInfo[policy];
          if (!info || !info.available_frequencies.length) return null;
          const freqs = info.available_frequencies;
          const currentMax = cpuMaxFreqs[policy] ?? freqs[freqs.length - 1];
          const idx = freqs.indexOf(currentMax);
          const labels = getPolicyLabels(cpuInfo);
          const live = liveCpuMax[policy];
          const liveStr = live && live !== currentMax ? ` (${Math.round(live / 1000)} MHz)` : "";
          return (
            <PanelSectionRow key={policy}>
              <SliderField
                label={labels[policy]}
                description={`${Math.round(currentMax / 1000)} MHz${liveStr}`}
                value={idx >= 0 ? idx : freqs.length - 1}
                min={0} max={freqs.length - 1} step={1}
                disabled={!editMode}
                onChange={(i) => handleCpuMaxChange(policy, i)}
              />
            </PanelSectionRow>
          );
        })}
      </PanelSection>

      <PanelSection title={`GPU${temps.gpu ? ` (${(temps.gpu / 1000).toFixed(0)}°C)` : ""}`}>
        <PanelSectionRow>
          {(() => {
            const freqs = gpuInfo.available_frequencies;
            const idx = freqs.indexOf(gpuMaxFreq);
            const liveStr = liveGpuMax && liveGpuMax !== gpuMaxFreq ? ` (${Math.round(liveGpuMax / 1000000)} MHz)` : "";
            return (
              <SliderField
                label="GPU"
                description={`${Math.round(gpuMaxFreq / 1000000)} MHz${liveStr}`}
                value={idx >= 0 ? idx : freqs.length - 1}
                min={0} max={freqs.length - 1} step={1}
                disabled={!editMode}
                onChange={(i) => handleGpuMaxChange(i)}
              />
            );
          })()}
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Fan Curve">
        <FanCurveEditor
          points={curvePoints}
          onChange={handleCurveChange}
          disabled={!editMode}
        />
      </PanelSection>
    </div>
  );
}

export default definePlugin(() => {
  const reg = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((e: {unAppID: number, bRunning: boolean}) => {
    if (e.bRunning) {
      state.runningAppId = e.unAppID;
      const app = appStore.GetAppOverviewByAppID(e.unAppID);
      state.runningGameName = app?.display_name ?? String(e.unAppID);
      getGameProfile(String(e.unAppID)).then((preset) => {
        if (preset) {
          state.activePreset = preset;
          applyPreset(preset);
        }
      });
    } else {
      state.runningAppId = 0;
      state.runningGameName = "";
      state.activePreset = "Default";
      applyPreset("Default");
    }
  });

  return {
    name: "ROCKNIX Control",
    title: <div>ROCKNIX Control</div>,
    content: <Content />,
    icon: <FaCog />,
    onDismount() { reg.unregister(); }
  };
});
