"""
Hardware stats aggregator — collects all sensor readings into a StatsSnapshot.
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StatsSnapshot:
    timestamp: float = 0.0
    # CPU
    cpu_percent: float = 0.0
    cpu_temp_c: float = 0.0
    cpu_freq_mhz: float = 0.0
    # RAM
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_percent: float = 0.0
    cpu_power_w: float = 0.0
    # SoC voltages (amdgpu hwmon)
    soc_vddgfx_v: float = 0.0
    soc_vddnb_v: float = 0.0
    # GPU (RTX 5070 via pynvml)
    gpu_percent: float = 0.0
    gpu_temp_c: float = 0.0
    gpu_vram_used_mb: float = 0.0
    gpu_vram_total_mb: float = 0.0
    gpu_power_w: float = 0.0
    # Disk
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_percent: float = 0.0
    # Network
    net_sent_mbps: float = 0.0
    net_recv_mbps: float = 0.0
    # System
    uptime_s: float = 0.0


RAPL_ENERGY_PATH = "/sys/class/powercap/intel-rapl:0/energy_uj"
RAPL_RANGE_PATH = "/sys/class/powercap/intel-rapl:0/max_energy_range_uj"
HWMON_DIR = Path("/sys/class/hwmon")
HWMON_AMDGPU = None


def rapl_delta(prev_uj: int, cur_uj: int, max_range_uj: int) -> int:
    """Energy used between two RAPL readings. The counter wraps at
    max_energy_range_uj (CPU-specific), not at 2**32."""
    if max_range_uj <= 0:
        max_range_uj = 2**32
    delta = cur_uj - prev_uj
    return delta + max_range_uj if delta < 0 else delta


# Find amdgpu hwmon path at import time (absent off Linux, e.g. sim on a Mac)
for _d in HWMON_DIR.iterdir() if HWMON_DIR.is_dir() else ():
    try:
        if (_d / "name").read_text().strip() == "amdgpu":
            HWMON_AMDGPU = _d
            break
    except Exception:
        pass


class StatsCollector:
    def __init__(self, config=None):
        import psutil

        self._config = config
        self._last_net_sent = 0
        self._last_net_recv = 0
        self._last_net_time = time.time()
        self._last_energy_uj: int | None = None  # no baseline until a good read
        self._last_energy_time: float = time.time()
        self._rapl_available = Path(RAPL_ENERGY_PATH).exists()
        self._rapl_range_uj = self._read_rapl_range_uj()
        if self._rapl_available:
            self._last_energy_uj = self._read_energy_uj()
            self._last_energy_time = time.time()
        self._gpu_available = self._init_gpu()
        # Prime psutil cpu_percent so first collect() returns real data
        psutil.cpu_percent(interval=None)

    def _init_gpu(self) -> bool:
        try:
            import pynvml

            pynvml.nvmlInit()
            return True
        except Exception:
            return False

    def collect(self) -> StatsSnapshot:
        import psutil

        snap = StatsSnapshot(timestamp=time.time())

        # ── CPU ───────────────────────────────────────────────────────────────
        snap.cpu_percent = psutil.cpu_percent(interval=None)
        freq = psutil.cpu_freq()
        snap.cpu_freq_mhz = freq.current if freq else 0.0
        snap.cpu_temp_c = self._read_cpu_temp()

        # ── RAM ───────────────────────────────────────────────────────────────
        mem = psutil.virtual_memory()
        snap.ram_total_gb = mem.total / 1e9
        snap.ram_used_gb = mem.used / 1e9
        snap.ram_percent = mem.percent

        # ── CPU power (RAPL) ──────────────────────────────────────────────────
        if self._rapl_available:
            snap.cpu_power_w = self._read_cpu_power()

        # ── SoC voltages (amdgpu hwmon) ───────────────────────────────────────
        if HWMON_AMDGPU:
            snap.soc_vddgfx_v, snap.soc_vddnb_v = self._read_soc_voltages()

        # ── GPU ───────────────────────────────────────────────────────────────
        if self._gpu_available:
            (
                snap.gpu_percent,
                snap.gpu_temp_c,
                snap.gpu_vram_used_mb,
                snap.gpu_vram_total_mb,
                snap.gpu_power_w,
            ) = self._read_gpu()

        # ── Disk ──────────────────────────────────────────────────────────────
        disk = psutil.disk_usage("/")
        snap.disk_total_gb = disk.total / 1e9
        snap.disk_used_gb = disk.used / 1e9
        snap.disk_percent = disk.percent

        # ── Network ───────────────────────────────────────────────────────────
        snap.net_sent_mbps, snap.net_recv_mbps = self._read_net()

        # ── Uptime ────────────────────────────────────────────────────────────
        snap.uptime_s = time.time() - psutil.boot_time()

        return snap

    def _read_cpu_temp(self) -> float:
        try:
            import psutil

            temps = psutil.sensors_temperatures()
            # Try common sensor names for AMD Ryzen 9 7950X
            for name in ("k10temp", "zenpower", "coretemp", "cpu_thermal"):
                if name in temps:
                    entries = temps[name]
                    # Prefer Tctl/Tdie
                    for e in entries:
                        if e.label in ("Tctl", "Tdie", "Package id 0"):
                            return e.current
                    return entries[0].current
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _read_soc_voltages() -> tuple[float, float]:
        try:
            vddgfx = int((HWMON_AMDGPU / "in0_input").read_text().strip()) / 1000.0
            vddnb = int((HWMON_AMDGPU / "in1_input").read_text().strip()) / 1000.0
            return vddgfx, vddnb
        except Exception:
            return 0.0, 0.0

    @staticmethod
    def _read_rapl_range_uj() -> int:
        try:
            value = int(Path(RAPL_RANGE_PATH).read_text().strip())
        except Exception:
            value = 0
        # Unknown or nonsense range: fall back to the old assumption.
        return value if value > 0 else 2**32

    def _read_energy_uj(self) -> int | None:
        try:
            return int(Path(RAPL_ENERGY_PATH).read_text().strip())
        except Exception:
            return None

    def _read_cpu_power(self) -> float:
        now = time.time()
        energy = self._read_energy_uj()
        if energy is None:
            # A failed read is not a counter wrap: skip it and keep the last baseline.
            return 0.0
        if self._last_energy_uj is None:
            self._last_energy_uj, self._last_energy_time = energy, now
            return 0.0
        dt = max(now - self._last_energy_time, 0.001)
        delta = rapl_delta(self._last_energy_uj, energy, self._rapl_range_uj)
        self._last_energy_uj = energy
        self._last_energy_time = now
        return delta / 1e6 / dt  # µJ → W

    def _read_gpu(self) -> tuple[float, float, float, float, float]:
        try:
            import pynvml

            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W
            return (
                float(util.gpu),
                float(temp),
                mem.used / 1e6,
                mem.total / 1e6,
                power,
            )
        except Exception:
            return 0.0, 0.0, 0.0, 0.0, 0.0

    def _read_net(self) -> tuple[float, float]:
        import psutil

        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - self._last_net_time, 0.001)
        sent = (net.bytes_sent - self._last_net_sent) / dt / 1e6
        recv = (net.bytes_recv - self._last_net_recv) / dt / 1e6
        self._last_net_sent = net.bytes_sent
        self._last_net_recv = net.bytes_recv
        self._last_net_time = now
        return max(0.0, sent), max(0.0, recv)
