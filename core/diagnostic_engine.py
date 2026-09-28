import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import psutil

from core.diagnostic_rules import evaluate_hardware
from core.result import DiagnosticResult
from core.severity import Severity
from core.thresholds import THRESHOLDS
from modules.hardware import HardwareInfo
from utils.profesional import AnalisisProfesional


logger = logging.getLogger("hardware_diagnostico")


@dataclass
class DiagnosticRun:
    timestamp: str
    mode: str
    data: Dict[str, Any]
    results: List[DiagnosticResult]

    @property
    def severity(self) -> Severity:
        actionable = [
            result.severity
            for result in self.results
            if result.severity >= Severity.ALERT
        ]
        if actionable:
            return max(actionable)
        if any(result.severity == Severity.NORMAL for result in self.results):
            return Severity.NORMAL
        return Severity.INFORMATION

    @property
    def findings(self) -> List[DiagnosticResult]:
        return self.results

    @property
    def component_statuses(self) -> Dict[str, Severity]:
        statuses = {}
        for finding in self.results:
            component = _component_group(finding.component, finding.code)
            current = statuses.get(component)
            if current is None or finding.severity > current:
                statuses[component] = finding.severity
        return statuses

    @property
    def summary(self) -> Dict[str, Any]:
        critical = sum(
            finding.severity == Severity.CRITICAL for finding in self.results
        )
        alerts = sum(finding.severity == Severity.ALERT for finding in self.results)
        information = sum(
            finding.severity == Severity.INFORMATION for finding in self.results
        )
        normal = sum(finding.severity == Severity.NORMAL for finding in self.results)
        return {
            "severity": self.severity.label,
            "critical": critical,
            "alerts": alerts,
            "problems": critical + alerts,
            "information": information,
            "normal": normal,
            "findings_count": len(self.results),
        }

    def to_dict(self, include_data=True) -> Dict[str, Any]:
        result = {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "summary": self.summary,
            "component_statuses": {
                component: severity.label
                for component, severity in self.component_statuses.items()
            },
            "findings": [finding.to_dict() for finding in self.results],
        }
        if include_data:
            result["data"] = self.data
        return result


class DiagnosticEngine:
    """Ejecuta módulos existentes y normaliza su resultado de salud."""

    def run_hardware_diagnostics(self, mode="normal", collector=None):
        logger.info("Diagnóstico de hardware iniciado | modo=%s", mode)
        hardware = collector or HardwareInfo()
        data = {}
        for key, method_name in (
            ("cpu", "cpu"),
            ("ram", "ram"),
            ("storage", "storage"),
            ("gpu", "gpu"),
            ("battery", "battery"),
            ("system", "system"),
        ):
            try:
                logger.info("Módulo de hardware iniciado | módulo=%s", key)
                data[key] = getattr(hardware, method_name)()
            except Exception:
                logger.exception(
                    "Error obteniendo datos del diagnóstico | módulo=%s", key
                )
                data[key] = _empty_section(key)

        try:
            from modules.temperatura import TemperaturaInfo

            logger.info("Módulo de hardware iniciado | módulo=temperaturas")
            data["temperature_sensors"] = TemperaturaInfo().obtener()
        except Exception:
            logger.exception("Error obteniendo lecturas de temperatura")
            data["temperature_sensors"] = {}

        self._sample_cpu(data.get("cpu", {}))
        findings = evaluate_hardware(data)
        ram = data.get("ram") or {}
        ram_usage = ram.get("usage_percent")
        ram_available = ram.get("available_gb")
        if (
            (
                isinstance(ram_usage, (int, float))
                and ram_usage >= THRESHOLDS.ram_elevated_percent
            )
            or (
                isinstance(ram_available, (int, float))
                and ram_available < THRESHOLDS.ram_low_available_gb
            )
        ):
            try:
                from modules.procesos import ProcesosInfo

                logger.info("Módulo de procesos iniciado | motivo=RAM elevada")
                data["processes"] = ProcesosInfo.obtener_detalle_memoria()
            except Exception:
                logger.exception(
                    "Error obteniendo procesos con mayor consumo de memoria"
                )
                data["processes"] = {"top_memory": []}
        else:
            data["processes"] = {"top_memory": []}

        run = DiagnosticRun(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            mode=mode,
            data=data,
            results=findings,
        )
        logger.info(
            "Diagnóstico finalizado | hallazgos=%s | alertas=%s | críticos=%s | estado=%s",
            len(findings),
            run.summary["alerts"],
            run.summary["critical"],
            run.severity.label,
        )
        return run

    @staticmethod
    def _sample_cpu(cpu):
        if not cpu:
            return
        samples = []
        for _ in range(THRESHOLDS.cpu_samples):
            try:
                value = psutil.cpu_percent(
                    interval=THRESHOLDS.cpu_sample_interval_seconds
                )
                if isinstance(value, (int, float)) and 0 <= value <= 100:
                    samples.append(float(value))
            except (OSError, RuntimeError):
                logger.warning("Falló una muestra de uso de CPU", exc_info=True)
                break
        cpu["usage_samples_percent"] = samples
        cpu["usage_sample_duration_seconds"] = round(
            len(samples) * THRESHOLDS.cpu_sample_interval_seconds, 1
        )
        if samples:
            cpu["usage_percent"] = round(sum(samples) / len(samples), 1)

    def ejecutar(self, modulos, modo: str) -> DiagnosticRun:
        datos = {}
        resultados = []
        for modulo in modulos:
            try:
                datos[modulo.nombre] = modulo.obtener()
            except Exception as error:
                logger.exception("Error ejecutando el módulo %s", modulo.nombre)
                resultados.append(
                    DiagnosticResult(
                        code="MODULE_ERROR",
                        title=f"Error en {modulo.nombre}",
                        description="No fue posible completar este módulo.",
                        evidence={"error": str(error)},
                        severity=Severity.CRITICAL,
                        recommendation="Revisa el archivo de registro para conocer el error.",
                    )
                )

        resumen = AnalisisProfesional.resumen(datos)
        severidad = Severity.INFORMATION
        descripcion = (
            "No hay métricas suficientes para evaluar el estado de salud."
        )
        if self._tiene_metricas(datos):
            severidad = {
                "OK": Severity.NORMAL,
                "ALERTA": Severity.ALERT,
                "CRÍTICO": Severity.CRITICAL,
            }.get(resumen["estado"], Severity.INFORMATION)
            descripcion = (
                f"Evaluación de salud: {resumen['estado']} "
                f"(puntuación {resumen['score']}/100)."
            )
        resultados.insert(
            0,
            DiagnosticResult(
                code="SYSTEM_HEALTH",
                title="Estado general del equipo",
                description=descripcion,
                evidence={
                    "score": resumen["score"],
                    "hallazgos": resumen["hallazgos"],
                },
                severity=severidad,
                recommendation=resumen["recomendacion"],
            ),
        )
        return DiagnosticRun(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            mode=modo,
            data=datos,
            results=resultados,
        )

    @staticmethod
    def _tiene_metricas(datos: Dict[str, dict]) -> bool:
        cpu = datos.get("CPU", {})
        ram = datos.get("RAM", {})
        discos = datos.get("Discos", {})
        bateria = datos.get("Batería", {})
        temperatura = datos.get("Temperatura", {})
        gpu = datos.get("GPU", {})
        return any(
            (
                "Uso actual" in cpu,
                "Porcentaje de uso" in ram,
                bool(discos.get("particiones")),
                "Porcentaje" in bateria,
                any(isinstance(valor, dict) for valor in temperatura.values()),
                any("Temperatura" in tarjeta for tarjeta in gpu.get("gpus", [])),
            )
        )


def run_hardware_diagnostics(mode="normal", collector=None):
    """Collect hardware data, run deterministic rules, and return findings."""
    return DiagnosticEngine().run_hardware_diagnostics(mode, collector)


def _component_group(component, code=""):
    if "TEMPERATURE" in code or "TEMPERATURA" in code:
        return "TEMPERATURAS"
    normalized = component.upper()
    if normalized.startswith("CPU"):
        return "CPU"
    if normalized.startswith("RAM"):
        return "RAM"
    if normalized.startswith("DISCO") or normalized.startswith("ALMACENAMIENTO"):
        return "DISCO"
    if normalized.startswith("GPU"):
        return "GPU"
    if normalized.startswith("BATERÍA"):
        return "BATERÍA"
    if normalized.startswith("TEMP"):
        return "TEMPERATURAS"
    if normalized.startswith("SISTEMA"):
        return "SISTEMA"
    return component


def _empty_section(name):
    return {
        "cpu": {},
        "ram": {},
        "storage": {"physical_drives": [], "volumes": []},
        "gpu": {"cards": []},
        "battery": {"detected": False},
        "system": {},
        "temperature_sensors": {},
    }.get(name, {})
