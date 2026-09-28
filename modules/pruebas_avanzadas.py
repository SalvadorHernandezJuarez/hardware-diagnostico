"""Bounded, non-destructive hardware and connectivity tests."""

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

import psutil

from core.result import DiagnosticResult
from core.severity import Severity
from core.thresholds import THRESHOLDS
from modules.hardware import HardwareInfo
from modules.red import NetworkDiagnostics


logger = logging.getLogger("hardware_diagnostico")

ADVANCED_TEST_THRESHOLDS = {
    "cpu_test_max_seconds": 15,
    "cpu_sample_interval_seconds": 1.0,
    "cpu_temperature_stop_c": THRESHOLDS.cpu_temperature_critical_c,
    "memory_test_max_bytes": 16 * 1024 * 1024,
    "storage_test_max_bytes": 4 * 1024 * 1024,
    "stability_min_seconds": 10,
    "stability_max_seconds": 120,
    "stability_sample_interval_seconds": 1.0,
}

def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AdvancedTestResult:
    started_at: str
    finished_at: str
    duration_seconds: float
    diagnostic: DiagnosticResult
    measurements: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def severity(self):
        return self.diagnostic.severity

    @property
    def code(self):
        return self.diagnostic.code

    def to_dict(self):
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "diagnostic": self.diagnostic.to_dict(),
            "measurements": self.measurements,
            "errors": self.errors,
            "cancelled": self.cancelled,
        }


@dataclass
class AdvancedDiagnosticRun:
    started_at: str
    finished_at: str
    duration_seconds: float
    results: List[AdvancedTestResult]
    severity: Severity
    cancelled: bool = False

    def to_dict(self):
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "results": [result.to_dict() for result in self.results],
            "severity": self.severity.label,
            "cancelled": self.cancelled,
        }


class AdvancedDiagnostics:
    """Runs short tests and reports measurements without modifying system setup."""

    def __init__(self, hardware=None, network=None, clock=None, sleeper=None):
        self.hardware = hardware or HardwareInfo()
        self.network = network or NetworkDiagnostics()
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep

    def cpu_test(self, duration_seconds=5, cancel_event=None):
        duration = _bounded_number(
            duration_seconds,
            1,
            ADVANCED_TEST_THRESHOLDS["cpu_test_max_seconds"],
            5,
        )
        started_at = _timestamp()
        started = self._clock()
        self._log_start("CPU")
        errors = []
        before = self._cpu_info(errors)
        temperatures = []
        usages = []
        frequencies = []
        stop_event = threading.Event()
        interrupted = False
        try:
            initial_temperature = _number(before.get("temperature_c"))
            if (
                initial_temperature is not None
                and initial_temperature
                >= ADVANCED_TEST_THRESHOLDS["cpu_temperature_stop_c"]
            ):
                stop_event.set()
            else:
                self._sample_cpu(
                    started, duration, cancel_event, stop_event, usages,
                    temperatures, frequencies, errors,
                )
        except KeyboardInterrupt:
            interrupted = True
            if cancel_event:
                cancel_event.set()
        finally:
            stop_event.set()

        after = self._cpu_info(errors)
        cpu_temperature_values = [
            value for value in temperatures if value is not None
        ]
        before_temperature = _number(before.get("temperature_c"))
        after_temperature = _number(after.get("temperature_c"))
        if before_temperature is not None:
            cpu_temperature_values.insert(0, before_temperature)
        if after_temperature is not None:
            cpu_temperature_values.append(after_temperature)
        max_temperature = max(cpu_temperature_values) if cpu_temperature_values else None
        cancelled = interrupted or bool(cancel_event and cancel_event.is_set())
        dangerous = (
            max_temperature is not None
            and max_temperature >= ADVANCED_TEST_THRESHOLDS["cpu_temperature_stop_c"]
        )
        if dangerous:
            severity = Severity.CRITICAL
            code = "ADVANCED_CPU_DANGEROUS_TEMPERATURE"
            description = "Se alcanzó el umbral de temperatura para detener la prueba."
            recommendation = "Detener cargas y revisar refrigeración antes de repetir."
        elif errors:
            severity = Severity.ALERT
            code = "ADVANCED_CPU_TEST_ERROR"
            description = "La prueba de CPU tuvo errores de medición o ejecución."
            recommendation = "Revisar los errores y repetir solo si el equipo está estable."
        elif before.get("status") and str(before["status"]).casefold() not in (
            "ok", "unknown",
        ):
            severity = Severity.ALERT
            code = "ADVANCED_CPU_REPORTED_STATUS"
            description = "El firmware o Windows reporta un estado anómalo del procesador."
            recommendation = "Revisar el estado del procesador reportado por Windows."
        elif max_temperature is not None and max_temperature >= THRESHOLDS.cpu_temperature_high_c:
            severity = Severity.ALERT
            code = "ADVANCED_CPU_HIGH_TEMPERATURE"
            description = "Se observó temperatura elevada durante la prueba breve."
            recommendation = "Revisar ventilación y refrigeración del procesador."
        elif cancelled:
            severity = Severity.INFORMATION
            code = "ADVANCED_CPU_TEST_CANCELLED"
            description = "La prueba de CPU fue cancelada de forma segura."
            recommendation = ""
        elif not cpu_temperature_values:
            severity = Severity.INFORMATION
            code = "ADVANCED_CPU_TEMPERATURE_UNAVAILABLE"
            description = "La carga breve terminó, pero no hay sensor térmico de CPU disponible."
            recommendation = "El resultado no evalúa temperatura ni sustituye una prueba especializada."
        else:
            severity = Severity.NORMAL
            code = "ADVANCED_CPU_TEST_NORMAL"
            description = "La prueba breve terminó sin errores reportados."
            recommendation = ""
        measurements = {
            "model": before.get("model"),
            "physical_cores": before.get("physical_cores"),
            "threads": before.get("threads"),
            "reported_status": before.get("status"),
            "usage_before_percent": before.get("usage_percent"),
            "usage_samples_percent": usages,
            "usage_max_percent": max(usages) if usages else None,
            "frequency_samples_mhz": frequencies,
            "temperature_before_c": before.get("temperature_c"),
            "temperature_samples_c": temperatures,
            "temperature_max_c": max_temperature,
            "temperature_during_available": any(
                value is not None for value in temperatures
            ),
            "duration_requested_seconds": duration,
            "duration_actual_seconds": round(self._clock() - started, 2),
            "thresholds": {
                "high_temperature_c": THRESHOLDS.cpu_temperature_high_c,
                "stop_temperature_c": ADVANCED_TEST_THRESHOLDS[
                    "cpu_temperature_stop_c"
                ],
            },
        }
        return self._finish(
            started_at,
            started,
            code,
            "Prueba de CPU",
            "CPU",
            severity,
            description,
            measurements,
            recommendation,
            errors,
            cancelled,
        )

    def _sample_cpu(
        self,
        started,
        duration,
        cancel_event,
        stop_event,
        usages,
        temperatures,
        frequencies,
        errors,
    ):
        worker = threading.Thread(
            target=lambda: self._bounded_cpu_worker(stop_event),
            name="hardware-diagnostico-cpu-load",
            daemon=True,
        )
        worker.start()
        interval = ADVANCED_TEST_THRESHOLDS["cpu_sample_interval_seconds"]
        try:
            while self._clock() - started < duration:
                if cancel_event and cancel_event.is_set():
                    break
                if stop_event.wait(min(interval, max(0.0, duration - (self._clock() - started)))):
                    break
                try:
                    usages.append(float(psutil.cpu_percent(interval=None)))
                except (OSError, RuntimeError, psutil.Error) as error:
                    errors.append(f"CPU usage: {error}")
                try:
                    cpu = self.hardware.cpu()
                    temperature = _number(cpu.get("temperature_c"))
                    frequency = _number(cpu.get("current_frequency_mhz"))
                    if frequency is not None:
                        frequencies.append(frequency)
                except Exception as error:
                    logger.info("No se pudo leer telemetría de CPU durante la prueba: %s", error)
                    errors.append(f"CPU telemetry: {error}")
                    temperature = None
                temperatures.append(temperature)
                if (
                    temperature is not None
                    and temperature >= ADVANCED_TEST_THRESHOLDS["cpu_temperature_stop_c"]
                ):
                    stop_event.set()
                    break
        except KeyboardInterrupt:
            if cancel_event:
                cancel_event.set()
            else:
                raise
        finally:
            stop_event.set()
            worker.join(timeout=2)

    @staticmethod
    def _bounded_cpu_worker(stop_event):
        value = 1
        while not stop_event.is_set():
            for _ in range(10000):
                value = (value * 3 + 1) % 1000003
            time.sleep(0)

    def _cpu_info(self, errors):
        try:
            cpu = self.hardware.cpu()
            return cpu if isinstance(cpu, dict) else {}
        except Exception as error:
            logger.exception("No se pudo consultar CPU para prueba avanzada")
            errors.append(f"CPU information: {error}")
            return {}

    def ram_test(self):
        started_at = _timestamp()
        started = self._clock()
        self._log_start("RAM")
        errors = []
        try:
            memory = psutil.virtual_memory()
            total = int(memory.total)
            available = int(memory.available)
            amount = min(
                ADVANCED_TEST_THRESHOLDS["memory_test_max_bytes"],
                max(0, available // 16),
            )
            amount = max(0, amount)
            if amount < 1024 * 1024:
                raise MemoryError("Memoria disponible insuficiente para la prueba básica.")
            buffer = bytearray(amount)
            chunk_size = 64 * 1024
            expected = bytes((index % 251 for index in range(chunk_size)))
            for offset in range(0, amount, chunk_size):
                length = min(chunk_size, amount - offset)
                buffer[offset:offset + length] = expected[:length]
            verified = all(
                buffer[offset:offset + min(chunk_size, amount - offset)]
                == expected[:min(chunk_size, amount - offset)]
                for offset in range(0, amount, chunk_size)
            )
            del buffer
            measurements = {
                "total_bytes": total,
                "available_before_bytes": available,
                "used_before_bytes": int(memory.used),
                "usage_percent_before": float(memory.percent),
                "tested_bytes": amount,
                "tested_mb": round(amount / (1024 ** 2), 2),
                "pattern_verified": verified,
                "limitations": (
                    "Prueba superficial de memoria asignable por Windows; "
                    "no sustituye Windows Memory Diagnostic ni MemTest86."
                ),
            }
            severity = Severity.NORMAL if verified else Severity.CRITICAL
            code = (
                "ADVANCED_RAM_BASIC_TEST_NORMAL"
                if verified else "ADVANCED_RAM_PATTERN_MISMATCH"
            )
            description = (
                "La prueba básica de escritura y lectura en memoria virtualizable terminó."
                if verified else "Los datos leídos no coinciden con el patrón de prueba."
            )
            recommendation = (
                "" if verified
                else "Ejecutar una prueba especializada de memoria fuera del sistema operativo."
            )
        except (MemoryError, OSError, psutil.Error) as error:
            logger.warning("Prueba básica de RAM no pudo completarse: %s", error)
            errors.append(str(error))
            measurements = {"tested_bytes": 0, "pattern_verified": None}
            severity = Severity.INFORMATION
            code = "ADVANCED_RAM_TEST_UNAVAILABLE"
            description = "No fue posible completar la prueba básica de memoria."
            recommendation = (
                "Para una comprobación exhaustiva, utilizar Windows Memory Diagnostic "
                "o una herramienta especializada arrancable."
            )
        return self._finish(
            started_at, started, code, "Prueba básica de RAM", "RAM", severity,
            description, measurements, recommendation, errors,
        )

    def storage_test(self):
        started_at = _timestamp()
        started = self._clock()
        self._log_start("ALMACENAMIENTO")
        errors = []
        measurements = {}
        try:
            storage = self.hardware.storage()
            volumes = storage.get("volumes", [])
            drives = storage.get("physical_drives", [])
            measurements.update(
                {
                    "volumes": [
                        {
                            "mountpoint": volume.get("mountpoint"),
                            "free_bytes": volume.get("free_bytes"),
                            "total_bytes": volume.get("total_bytes"),
                            "free_percent": (
                                round(volume["free_bytes"] * 100 / volume["total_bytes"], 1)
                                if volume.get("free_bytes") is not None
                                and volume.get("total_bytes")
                                else None
                            ),
                        }
                        for volume in volumes
                    ],
                    "physical_drives": [
                        {
                            "model": drive.get("model"),
                            "health": drive.get("health"),
                            "temperature_c": drive.get("temperature_c"),
                            "status": drive.get("status"),
                        }
                        for drive in drives
                    ],
                }
            )
        except Exception as error:
            logger.exception("Falló el inventario de almacenamiento en prueba avanzada")
            errors.append(f"Storage inventory: {error}")
            volumes, drives = [], []

        read_write = self._safe_storage_read_write(errors)
        measurements["read_write_test"] = read_write
        severity = Severity.NORMAL
        code = "ADVANCED_STORAGE_TEST_NORMAL"
        description = "La revisión no encontró indicadores disponibles de falla."
        recommendation = ""
        for drive in drives:
            health = str(drive.get("health") or "").casefold()
            if health in ("problem", "unhealthy", "failed", "error"):
                severity = Severity.CRITICAL
                code = "ADVANCED_STORAGE_SMART_FAILURE"
                description = "Windows reporta un estado de salud problemático en una unidad."
                recommendation = "Respaldar los datos importantes y revisar la unidad."
                break
            if health in ("warning", "caution", "degraded"):
                severity = max(severity, Severity.ALERT)
                code = "ADVANCED_STORAGE_SMART_WARNING"
                description = "La unidad reporta un indicador SMART de advertencia."
                recommendation = "Respaldar datos y revisar la salud de la unidad."
        low_space = [
            item for item in measurements.get("volumes", [])
            if item["free_percent"] is not None
            and item["free_percent"] < THRESHOLDS.disk_free_alert_percent
        ]
        critical_space = [
            item for item in low_space
            if item["free_percent"] < THRESHOLDS.disk_free_critical_percent
        ]
        if critical_space and severity < Severity.CRITICAL:
            severity = Severity.CRITICAL
            code = "ADVANCED_STORAGE_CRITICAL_SPACE"
            description = "Una o más unidades tienen espacio libre críticamente bajo."
            recommendation = "Liberar espacio de forma controlada y respaldar información."
        elif low_space and severity < Severity.ALERT:
            severity = Severity.ALERT
            code = "ADVANCED_STORAGE_LOW_SPACE"
            description = "Una o más unidades tienen poco espacio libre."
            recommendation = "Revisar el uso del almacenamiento y conservar espacio libre."
        if errors and severity < Severity.ALERT:
            severity = Severity.ALERT
            code = "ADVANCED_STORAGE_TEST_ERROR"
            description = "No se pudieron completar todas las comprobaciones de almacenamiento."
            recommendation = "Repetir la prueba y revisar los errores de acceso."
        if not volumes and not drives and not errors:
            severity = Severity.INFORMATION
            code = "ADVANCED_STORAGE_UNAVAILABLE"
            description = "No se obtuvo información de unidades o volúmenes para evaluar."
            recommendation = ""
        measurements["thresholds"] = {
            "minimum_free_percent": THRESHOLDS.disk_free_alert_percent,
            "smart": "SMART/HealthStatus depende del proveedor y puede no estar disponible.",
        }
        return self._finish(
            started_at, started, code, "Prueba de almacenamiento", "ALMACENAMIENTO",
            severity, description, measurements, recommendation, errors,
        )

    def _safe_storage_read_write(self, errors):
        size = ADVANCED_TEST_THRESHOLDS["storage_test_max_bytes"]
        path = None
        outcome = {
            "tested_bytes": 0,
            "write_read_verified": None,
            "temporary_file_removed": False,
        }
        try:
            descriptor, path = tempfile.mkstemp(prefix="hardware-diagnostico-test-")
            pattern = bytes(range(256)) * (size // 256)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(pattern)
                stream.flush()
                os.fsync(stream.fileno())
            with open(path, "rb") as stream:
                verified = stream.read() == pattern
            if not verified:
                errors.append("La verificación de lectura/escritura no coincidió.")
            outcome.update({
                "tested_bytes": size,
                "write_read_verified": verified,
            })
        except OSError as error:
            errors.append(f"Read/write test: {error}")
            outcome["error"] = str(error)
        finally:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as error:
                    errors.append(f"No se pudo eliminar el archivo temporal de prueba: {error}")
            outcome["temporary_file_removed"] = (
                path is None or not os.path.exists(path)
            )
        return outcome

    def gpu_test(self):
        started_at = _timestamp()
        started = self._clock()
        self._log_start("GPU")
        errors = []
        try:
            gpu = self.hardware.gpu()
            cards = gpu.get("cards", [])
        except Exception as error:
            logger.exception("No se pudo consultar GPU")
            cards = []
            errors.append(f"GPU query: {error}")
        measurements = {
            "detected": bool(cards),
            "cards": cards,
            "load_test": "No se ejecutó carga sintética; solo se tomaron métricas disponibles.",
        }
        problematic = [
            card for card in cards
            if str(card.get("status") or "").casefold() in (
                "error", "failed", "degraded",
            )
        ]
        hot = [
            card for card in cards
            if card.get("temperature_c") is not None
            and card["temperature_c"] >= THRESHOLDS.gpu_temperature_high_c
        ]
        critically_hot = [
            card for card in cards
            if card.get("temperature_c") is not None
            and card["temperature_c"] >= THRESHOLDS.gpu_temperature_critical_c
        ]
        if critically_hot:
            severity = Severity.CRITICAL
            code = "ADVANCED_GPU_CRITICAL_TEMPERATURE"
            description = "La temperatura reportada por la GPU alcanzó el umbral crítico."
            recommendation = "Detener cargas gráficas y revisar refrigeración."
        elif problematic or hot:
            severity = Severity.ALERT
            code = "ADVANCED_GPU_INDICATOR"
            description = "Se detectó un indicador reportado por la GPU que requiere revisión."
            recommendation = "Revisar el controlador, la refrigeración y el estado informado."
        elif errors:
            severity = Severity.ALERT
            code = "ADVANCED_GPU_TEST_ERROR"
            description = "No fue posible completar la consulta de GPU."
            recommendation = "Revisar permisos y disponibilidad del proveedor de GPU."
        elif cards:
            severity = Severity.NORMAL
            code = "ADVANCED_GPU_TEST_NORMAL"
            description = "Se consultaron las métricas disponibles de la GPU."
            recommendation = ""
        else:
            severity = Severity.INFORMATION
            code = "ADVANCED_GPU_UNAVAILABLE"
            description = "No se detectó una GPU o sus métricas no están disponibles."
            recommendation = ""
        measurements["thresholds"] = {
            "high_temperature_c": THRESHOLDS.gpu_temperature_high_c,
            "stop_temperature_c": THRESHOLDS.gpu_temperature_critical_c,
        }
        return self._finish(
            started_at, started, code, "Prueba de GPU", "GPU", severity,
            description, measurements, recommendation, errors,
        )

    def battery_test(self):
        started_at = _timestamp()
        started = self._clock()
        self._log_start("BATERÍA")
        errors = []
        try:
            battery = self.hardware.battery()
        except Exception as error:
            logger.exception("No se pudo consultar la batería")
            battery = {"detected": False}
            errors.append(f"Battery query: {error}")
        if not battery.get("detected"):
            severity = Severity.INFORMATION
            code = "ADVANCED_BATTERY_UNAVAILABLE"
            description = "No se detectó batería en el equipo."
            recommendation = ""
        else:
            health = battery.get("health_percent")
            if health is not None and health < THRESHOLDS.battery_health_low_percent:
                severity = Severity.ALERT
                code = "ADVANCED_BATTERY_WEAR"
                description = "La capacidad máxima reportada está por debajo del umbral de salud."
                recommendation = "Revisar autonomía y considerar servicio de batería."
            elif errors:
                severity = Severity.ALERT
                code = "ADVANCED_BATTERY_TEST_ERROR"
                description = "La consulta de batería terminó con errores parciales."
                recommendation = "Revisar los errores y consultar el fabricante si persisten."
            else:
                severity = Severity.NORMAL
                code = "ADVANCED_BATTERY_TEST_NORMAL"
                description = "La información disponible de batería no indica desgaste elevado."
                recommendation = ""
            battery = {
                **battery,
                "wear_percent": (
                    max(0, round(100 - health, 1))
                    if health is not None else None
                ),
                "temperature_c": battery.get("temperature_c"),
            }
        return self._finish(
            started_at, started, code, "Prueba de batería", "BATERÍA", severity,
            description, battery, recommendation, errors,
        )

    def network_test(self):
        started_at = _timestamp()
        started = self._clock()
        self._log_start("RED")
        errors = []
        try:
            result = self.network.automatic_diagnostic()
            measurements = result.to_dict()
            severity = result.severity
            findings = result.findings
            description = result.diagnosis
            recommendation = result.recommendation
            code = (
                findings[0].code if findings else "ADVANCED_NETWORK_TEST_COMPLETE"
            )
        except Exception as error:
            logger.exception("Falló prueba avanzada de red")
            errors.append(f"Network diagnostic: {error}")
            measurements = {}
            severity = Severity.ALERT
            code = "ADVANCED_NETWORK_TEST_ERROR"
            description = "No fue posible completar las pruebas de conectividad."
            recommendation = "Revisar el módulo de diagnóstico de red."
        return self._finish(
            started_at, started, code, "Prueba de red", "RED", severity,
            description, measurements, recommendation, errors,
        )

    def stability_test(self, duration_seconds=30, cancel_event=None):
        duration = _bounded_number(
            duration_seconds,
            ADVANCED_TEST_THRESHOLDS["stability_min_seconds"],
            ADVANCED_TEST_THRESHOLDS["stability_max_seconds"],
            30,
        )
        started_at = _timestamp()
        started = self._clock()
        self._log_start("ESTABILIDAD")
        samples = []
        errors = []
        stop_reason = None
        thermal_warning = False
        high_ram_samples = 0
        interval = ADVANCED_TEST_THRESHOLDS["stability_sample_interval_seconds"]
        while self._clock() - started < duration:
            if cancel_event and cancel_event.is_set():
                break
            sample = {}
            try:
                sample["cpu_usage_percent"] = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                sample["ram_usage_percent"] = memory.percent
                sample["ram_available_bytes"] = memory.available
                if memory.percent >= THRESHOLDS.ram_high_percent:
                    high_ram_samples += 1
            except (OSError, RuntimeError, psutil.Error) as error:
                errors.append(f"System metrics: {error}")
            try:
                cpu = self.hardware.cpu()
                sample["cpu_temperature_c"] = cpu.get("temperature_c")
                if (
                    sample["cpu_temperature_c"] is not None
                    and sample["cpu_temperature_c"]
                    >= ADVANCED_TEST_THRESHOLDS["cpu_temperature_stop_c"]
                ):
                    stop_reason = "Temperatura de CPU alcanzó umbral de parada."
                elif (
                    sample["cpu_temperature_c"] is not None
                    and sample["cpu_temperature_c"] >= THRESHOLDS.cpu_temperature_high_c
                ):
                    thermal_warning = True
            except Exception as error:
                errors.append(f"CPU metrics: {error}")
            try:
                gpu = self.hardware.gpu()
                sample["gpu"] = [
                    {
                        "name": card.get("name"),
                        "usage_percent": card.get("usage_percent"),
                        "temperature_c": card.get("temperature_c"),
                    }
                    for card in gpu.get("cards", [])
                ]
                if any(
                    card.get("temperature_c") is not None
                    and card["temperature_c"] >= THRESHOLDS.gpu_temperature_critical_c
                    for card in gpu.get("cards", [])
                ):
                    stop_reason = "Temperatura de GPU alcanzó umbral crítico."
                elif any(
                    card.get("temperature_c") is not None
                    and card["temperature_c"] >= THRESHOLDS.gpu_temperature_high_c
                    for card in gpu.get("cards", [])
                ):
                    thermal_warning = True
            except Exception as error:
                errors.append(f"GPU metrics: {error}")
            try:
                disk = psutil.disk_usage(os.path.abspath(os.sep))
                sample["disk_free_bytes"] = disk.free
                sample["disk_usage_percent"] = disk.percent
            except (OSError, RuntimeError, psutil.Error) as error:
                errors.append(f"Disk metrics: {error}")
            samples.append(sample)
            if stop_reason:
                break
            wait = min(interval, max(0, duration - (self._clock() - started)))
            if cancel_event:
                if cancel_event.wait(wait):
                    break
            else:
                self._sleep(wait)
        cancelled = bool(cancel_event and cancel_event.is_set())
        dangerous = bool(stop_reason)
        if dangerous:
            severity = Severity.CRITICAL
            code = "ADVANCED_STABILITY_TEMPERATURE_STOP"
            description = "La supervisión se detuvo al alcanzar un umbral térmico crítico."
            recommendation = "Dejar enfriar el equipo y revisar el sistema de refrigeración."
        elif errors:
            severity = Severity.ALERT
            code = "ADVANCED_STABILITY_TEST_ERRORS"
            description = "La prueba terminó con una o más métricas no disponibles."
            recommendation = "Revisar los errores; una lectura ausente no confirma una falla."
        elif cancelled:
            severity = Severity.INFORMATION
            code = "ADVANCED_STABILITY_TEST_CANCELLED"
            description = "La prueba de estabilidad fue cancelada de forma segura."
            recommendation = ""
        elif thermal_warning or high_ram_samples >= 2:
            severity = Severity.ALERT
            code = (
                "ADVANCED_STABILITY_HIGH_TEMPERATURE"
                if thermal_warning else "ADVANCED_STABILITY_HIGH_RAM"
            )
            description = (
                "Se observaron temperaturas elevadas durante la supervisión."
                if thermal_warning
                else "El uso de RAM permaneció elevado en varias muestras."
            )
            recommendation = (
                "Revisar refrigeración y repetir la prueba cuando el equipo esté inactivo."
                if thermal_warning
                else "Revisar procesos con alto consumo de memoria y repetir el diagnóstico."
            )
        else:
            severity = Severity.NORMAL
            code = "ADVANCED_STABILITY_TEST_NORMAL"
            description = "La supervisión terminó sin errores reportados."
            recommendation = ""
        measurements = {
            "duration_requested_seconds": duration,
            "duration_actual_seconds": round(self._clock() - started, 2),
            "sample_count": len(samples),
            "samples": samples,
            "stop_reason": stop_reason,
            "high_ram_samples": high_ram_samples,
            "thermal_warning": thermal_warning,
            "thresholds": {
                "cpu_stop_temperature_c": ADVANCED_TEST_THRESHOLDS[
                    "cpu_temperature_stop_c"
                ],
                "gpu_stop_temperature_c": THRESHOLDS.gpu_temperature_critical_c,
            },
        }
        return self._finish(
            started_at, started, code, "Prueba de estabilidad", "ESTABILIDAD",
            severity, description, measurements, recommendation, errors, cancelled,
        )

    def complete_test(self, cancel_event=None):
        started_at = _timestamp()
        started = self._clock()
        self._log_start("DIAGNÓSTICO COMPLETO")
        tests = (
            ("CPU", lambda: self.cpu_test(cancel_event=cancel_event)),
            ("RAM", self.ram_test),
            ("ALMACENAMIENTO", self.storage_test),
            ("GPU", self.gpu_test),
            ("BATERÍA", self.battery_test),
            ("RED", self.network_test),
        )
        results = []
        cancelled = False
        for component, operation in tests:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break
            try:
                results.append(operation())
            except KeyboardInterrupt:
                if cancel_event:
                    cancel_event.set()
                cancelled = True
                break
            except Exception as error:
                logger.exception("Falló la prueba completa: %s", component)
                results.append(
                    self._failed_test(component, error)
                )
        cancelled = cancelled or bool(cancel_event and cancel_event.is_set())
        severities = [result.severity for result in results]
        severity = max(severities) if severities else Severity.INFORMATION
        return AdvancedDiagnosticRun(
            started_at=started_at,
            finished_at=_timestamp(),
            duration_seconds=round(self._clock() - started, 2),
            results=results,
            severity=severity,
            cancelled=cancelled,
        )

    def _failed_test(self, component, error):
        now = self._clock()
        return self._finish(
            _timestamp(),
            now,
            f"ADVANCED_{_slug(component)}_TEST_ERROR",
            f"Prueba de {component}",
            component,
            Severity.ALERT,
            "La comprobación no pudo completarse.",
            {},
            "Revisar los errores registrados y repetir si procede.",
            [str(error)],
        )

    def _finish(
        self,
        started_at,
        started,
        code,
        title,
        component,
        severity,
        description,
        measurements,
        recommendation="",
        errors=None,
        cancelled=False,
    ):
        finished_at = _timestamp()
        duration = max(0, round(self._clock() - started, 2))
        errors = list(errors or [])
        diagnostic = DiagnosticResult(
            code=code,
            component=component,
            title=title,
            severity=severity,
            description=description,
            evidence={
                "measurements": measurements,
                "errors": errors,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": duration,
                "cancelled": cancelled,
            },
            current_value=measurements,
            expected_value="Dentro de los umbrales establecidos o no disponible.",
            recommendation=recommendation,
            confidence="MEDIA" if not errors else "BAJA",
            timestamp=finished_at,
            source="psutil / HardwareInfo / NetworkDiagnostics",
        )
        result = AdvancedTestResult(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            diagnostic=diagnostic,
            measurements=measurements,
            errors=errors,
            cancelled=cancelled,
        )
        logger.info(
            "Prueba avanzada finalizada | código=%s | severidad=%s | duración=%.2fs | errores=%d",
            code,
            severity.label,
            duration,
            len(errors),
        )
        return result

    @staticmethod
    def _log_start(component):
        logger.info(
            "Prueba avanzada iniciada | componente=%s | timestamp=%s",
            component,
            _timestamp(),
        )


def _bounded_number(value, minimum, maximum, default):
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        numeric = default
    return min(maximum, max(minimum, numeric))


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _slug(value):
    return "".join(
        character if character.isalnum() else "_"
        for character in str(value).upper()
    ).strip("_")
