"""Central thresholds and deterministic rule priorities for diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticThresholds:
    ram_elevated_percent: float = 80.0
    ram_high_percent: float = 90.0
    ram_critical_percent: float = 95.0
    ram_low_available_gb: float = 1.0

    cpu_sustained_percent: float = 85.0
    cpu_samples: int = 5
    cpu_sample_interval_seconds: float = 0.5

    cpu_temperature_high_c: float = 85.0
    cpu_temperature_critical_c: float = 95.0
    gpu_temperature_high_c: float = 85.0
    gpu_temperature_critical_c: float = 95.0
    storage_temperature_high_c: float = 60.0
    storage_temperature_critical_c: float = 70.0
    battery_temperature_high_c: float = 45.0
    battery_temperature_critical_c: float = 60.0

    disk_free_alert_percent: float = 15.0
    disk_free_critical_percent: float = 5.0
    disk_free_alert_gb: float = 15.0
    disk_free_critical_gb: float = 5.0

    battery_health_low_percent: float = 80.0
    battery_health_critical_wear_percent: float = 40.0
    battery_low_charge_percent: float = 10.0


THRESHOLDS = DiagnosticThresholds()

RULE_PRIORITIES = {
    "DISK_LOW_SPACE": 10,
    "DISK_CRITICAL_SPACE": 5,
    "DISK_SMART_FAILURE": 1,
    "DISK_SMART_WARNING": 8,
    "CPU_TEMPERATURE_CRITICAL": 2,
    "GPU_TEMPERATURE_CRITICAL": 3,
    "STORAGE_TEMPERATURE_CRITICAL": 4,
    "RAM_CRITICAL_USAGE": 10,
    "RAM_VERY_HIGH_USAGE": 15,
    "RAM_HIGH_USAGE": 20,
    "CPU_SUSTAINED_HIGH_USAGE": 25,
    "BATTERY_HEALTH_LOW": 30,
}
