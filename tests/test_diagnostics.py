import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.diagnostic_engine import DiagnosticEngine, DiagnosticRun
from core.diagnostic_rules import evaluate_hardware
from core.result import DiagnosticResult
from core.severity import Severity
from core.thresholds import THRESHOLDS
from modules.hardware import HardwareInfo
from modules.procesos import ProcesosInfo
from reports.exportar import ExportarPDF
from ui.diagnostics import (
    DiagnosticsMenu,
    GUIDED_OPTIONS,
    SUPPORTED_GUIDED_OPTIONS,
    _normal_evidence,
)


def _base_data():
    return {
        "cpu": {
            "usage_percent": 20,
            "usage_samples_percent": [20, 25, 22],
            "temperature_c": None,
        },
        "ram": {
            "usage_percent": 40,
            "available_gb": 8,
            "installed_gb": 16,
        },
        "storage": {
            "physical_drives": [
                {"model": "Test SSD", "health": None, "temperature_c": None}
            ],
            "volumes": [
                {
                    "letter": "C:\\",
                    "total_gb": 500,
                    "used_gb": 250,
                    "free_gb": 250,
                    "usage_percent": 50,
                }
            ],
        },
        "gpu": {"cards": [{"name": "Test GPU", "temperature_c": None, "status": "OK"}]},
        "battery": {
            "detected": True,
            "percentage": 80,
            "power_connected": True,
            "health_percent": None,
        },
        "system": {
            "os": "Windows test",
            "architecture": "AMD64",
            "uptime_seconds": 1000,
        },
    }


class DiagnosticRulesTests(unittest.TestCase):
    def test_ram_uses_central_thresholds_and_distinguishes_critical_usage(self):
        for percentage, expected_code, expected_severity in (
            (79.9, "RAM_USAGE_NORMAL", Severity.NORMAL),
            (80, "RAM_HIGH_USAGE", Severity.ALERT),
            (90, "RAM_VERY_HIGH_USAGE", Severity.ALERT),
            (95, "RAM_VERY_HIGH_USAGE", Severity.ALERT),
            (95.1, "RAM_CRITICAL_USAGE", Severity.CRITICAL),
        ):
            data = _base_data()
            data["ram"]["usage_percent"] = percentage
            data["ram"]["available_gb"] = 2
            findings = evaluate_hardware(data)
            ram_finding = next(
                finding for finding in findings if finding.component == "RAM"
            )
            self.assertEqual(ram_finding.code, expected_code)
            self.assertEqual(ram_finding.severity, expected_severity)

        self.assertEqual(THRESHOLDS.ram_elevated_percent, 80)
        self.assertEqual(THRESHOLDS.ram_high_percent, 90)
        self.assertEqual(THRESHOLDS.ram_critical_percent, 95)

    def test_cpu_spike_is_information_but_sustained_usage_is_alert(self):
        data = _base_data()
        data["cpu"]["usage_samples_percent"] = [100, 12, 10, 11, 12]
        findings = evaluate_hardware(data)
        spike = next(item for item in findings if item.code == "CPU_TRANSIENT_SPIKE")
        self.assertEqual(spike.severity, Severity.INFORMATION)

        data["cpu"]["usage_samples_percent"] = [90, 92, 88, 91, 90]
        findings = evaluate_hardware(data)
        sustained = next(
            item for item in findings if item.code == "CPU_SUSTAINED_HIGH_USAGE"
        )
        self.assertEqual(sustained.severity, Severity.ALERT)

    def test_unknown_temperature_and_smart_do_not_create_hardware_faults(self):
        findings = evaluate_hardware(_base_data())
        codes = {finding.code for finding in findings}

        self.assertIn("TEMPERATURE_UNAVAILABLE", codes)
        self.assertIn("DISK_SMART_UNAVAILABLE", codes)
        self.assertNotIn("CPU_TEMPERATURE_CRITICAL", codes)
        self.assertNotIn("DISK_SMART_FAILURE", codes)
        self.assertTrue(
            all(
                finding.severity != Severity.CRITICAL
                for finding in findings
                if finding.code in ("TEMPERATURE_UNAVAILABLE", "DISK_SMART_UNAVAILABLE")
            )
        )

    def test_disk_free_space_and_smart_are_evaluated_separately(self):
        data = _base_data()
        data["storage"]["volumes"][0].update(
            {"free_gb": 4, "used_gb": 496, "usage_percent": 99.2}
        )
        data["storage"]["physical_drives"][0]["health"] = "problem"
        findings = evaluate_hardware(data)
        by_code = {finding.code: finding for finding in findings}

        self.assertEqual(by_code["DISK_CRITICAL_SPACE"].severity, Severity.CRITICAL)
        self.assertEqual(by_code["DISK_SMART_FAILURE"].severity, Severity.CRITICAL)
        self.assertLess(
            by_code["DISK_SMART_FAILURE"].priority,
            by_code["DISK_CRITICAL_SPACE"].priority,
        )

    def test_battery_wear_is_alert_not_automatic_critical_failure(self):
        data = _base_data()
        data["battery"].update(
            {
                "health_percent": 35,
                "design_capacity_mwh": 60000,
                "full_charge_capacity_mwh": 21000,
            }
        )
        findings = evaluate_hardware(data)
        battery = next(
            finding for finding in findings if finding.code == "BATTERY_HEALTH_LOW"
        )
        self.assertEqual(battery.severity, Severity.ALERT)
        self.assertIn("no confirma", battery.description)

    def test_available_sensor_temperature_can_create_alert_without_false_unknown(self):
        data = _base_data()
        data["temperature_sensors"] = {
            "nvme / Composite": {
                "actual": THRESHOLDS.storage_temperature_critical_c,
                "alta": None,
                "critica": None,
            }
        }
        findings = evaluate_hardware(data)
        thermal = next(
            item for item in findings if item.code == "STORAGE_TEMPERATURE_CRITICAL"
        )
        self.assertEqual(thermal.severity, Severity.CRITICAL)
        self.assertNotIn(
            "TEMPERATURE_UNAVAILABLE",
            {finding.code for finding in findings},
        )

    def test_result_has_common_fields_and_is_ordered_by_severity_then_rule_priority(self):
        data = _base_data()
        data["ram"]["usage_percent"] = 96
        data["ram"]["available_gb"] = 0.2
        data["storage"]["volumes"][0].update(
            {"free_gb": 2, "used_gb": 498, "usage_percent": 99.6}
        )
        findings = evaluate_hardware(data)

        self.assertEqual(findings, sorted(
            findings, key=lambda item: (-int(item.severity), item.priority, item.timestamp)
        ))
        for finding in findings:
            self.assertTrue(finding.code)
            self.assertTrue(finding.component)
            self.assertTrue(finding.title)
            self.assertTrue(finding.timestamp)
            self.assertIsNotNone(finding.confidence)
            self.assertIn("severity", finding.to_dict())


class DiagnosticEngineTests(unittest.TestCase):
    def test_battery_health_is_derived_only_when_both_capacities_exist(self):
        query_values = {
            "Win32_Battery": [],
            "BatteryStaticData": [{"DesignedCapacity": 60000}],
            "BatteryFullChargedCapacity": [{"FullChargedCapacity": 48000}],
            "BatteryCycleCount": [{"CycleCount": 350}],
        }
        with (
            patch(
                "modules.hardware.psutil.sensors_battery",
                return_value=SimpleNamespace(
                    percent=70,
                    power_plugged=False,
                    secsleft=1800,
                ),
            ),
            patch.object(
                HardwareInfo,
                "_query",
                side_effect=lambda name, **_kwargs: query_values.get(name, []),
            ),
        ):
            battery = HardwareInfo().battery()

        self.assertEqual(battery["health_percent"], 80)
        self.assertEqual(battery["cycle_count"], 350)

    def test_collection_error_is_logged_without_stopping_other_modules(self):
        class Collector:
            def cpu(self):
                return {
                    "usage_percent": 10,
                    "temperature_c": None,
                }

            def ram(self):
                return {"usage_percent": 30, "available_gb": 8, "installed_gb": 16}

            def storage(self):
                raise OSError("storage provider unavailable")

            def gpu(self):
                return {"cards": []}

            def battery(self):
                return {"detected": False}

            def system(self):
                return {"os": "Windows", "architecture": "x64"}

        with (
            patch.object(
                DiagnosticEngine,
                "_sample_cpu",
                side_effect=lambda cpu: cpu.update(
                    usage_samples_percent=[10, 12, 10, 11, 12],
                    usage_sample_duration_seconds=2.5,
                ),
            ),
            self.assertLogs("hardware_diagnostico", level="ERROR"),
        ):
            run = DiagnosticEngine().run_hardware_diagnostics(collector=Collector())

        self.assertEqual(run.data["storage"]["volumes"], [])
        self.assertTrue(any(item.code == "DISK_DATA_UNAVAILABLE" for item in run.findings))
        self.assertTrue(any(item.code == "RAM_USAGE_NORMAL" for item in run.findings))

    def test_summary_counts_findings_and_does_not_promote_information_over_normal(self):
        run = DiagnosticRun(
            timestamp="2026-01-01T00:00:00+00:00",
            mode="normal",
            data={},
            results=[
                DiagnosticResult(
                    code="NORMAL",
                    component="RAM",
                    title="Normal",
                    description="OK",
                    severity=Severity.NORMAL,
                ),
                DiagnosticResult(
                    code="INFO",
                    component="TEMPERATURA",
                    title="No disponible",
                    description="No sensor",
                    severity=Severity.INFORMATION,
                ),
                DiagnosticResult(
                    code="ALERT",
                    component="DISCO C:",
                    title="Poco espacio",
                    description="Espacio bajo",
                    severity=Severity.ALERT,
                ),
            ],
        )

        self.assertEqual(run.severity, Severity.ALERT)
        self.assertEqual(run.summary["problems"], 1)
        self.assertEqual(run.summary["alerts"], 1)
        self.assertEqual(run.summary["information"], 1)
        self.assertEqual(run.component_statuses["DISCO"], Severity.ALERT)

    def test_process_memory_snapshot_uses_real_rss_without_pid_in_report(self):
        process_one = Mock()
        process_one.info = {
            "name": "large.exe",
            "memory_info": type("MemoryInfo", (), {"rss": 3 * 1024 ** 3})(),
        }
        process_two = Mock()
        process_two.info = {
            "name": "small.exe",
            "memory_info": type("MemoryInfo", (), {"rss": 512 * 1024 ** 2})(),
        }
        with patch(
            "modules.procesos.psutil.process_iter",
            return_value=[process_two, process_one],
        ):
            result = ProcesosInfo.obtener_detalle_memoria()

        self.assertEqual(result["top_memory"][0]["name"], "large.exe")
        self.assertEqual(result["top_memory"][0]["rss_mb"], 3072)
        self.assertNotIn("pid", result["top_memory"][0])

    def test_diagnostic_pdf_uses_findings_summary(self):
        run = DiagnosticRun(
            timestamp="2026-09-27T12:00:00-06:00",
            mode="profesional",
            data={},
            results=[
                DiagnosticResult(
                    code="DISK_LOW_SPACE",
                    component="DISCO C:",
                    title="Espacio disponible reducido",
                    description="El espacio es bajo (< 15%).",
                    severity=Severity.ALERT,
                    recommendation="Revisar archivos grandes.",
                    current_value=10,
                    expected_value="> 15%",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("reports.exportar.RUTA_REPORTES", directory),
                patch("builtins.input", return_value=""),
                redirect_stdout(StringIO()),
            ):
                ExportarPDF.generar_diagnostico(run)
            exported = [
                path for path in os.listdir(directory) if path.endswith(".pdf")
            ]

        self.assertEqual(len(exported), 1)


class DiagnosticMenuTests(unittest.TestCase):
    def test_general_diagnostic_presents_summary_without_printing_from_engine(self):
        run = DiagnosticRun(
            timestamp="2026-09-27T12:00:00-06:00",
            mode="normal",
            data={},
            results=[
                DiagnosticResult(
                    code="RAM_HIGH_USAGE",
                    component="RAM",
                    title="Uso elevado de memoria",
                    description="Se detecta uso elevado.",
                    severity=Severity.ALERT,
                    recommendation="Revisar los procesos.",
                )
            ],
        )
        output = StringIO()
        menu = DiagnosticsMenu(Mock())
        with (
            patch("ui.diagnostics.run_hardware_diagnostics", return_value=run),
            patch("builtins.input", return_value="0"),
            redirect_stdout(output),
        ):
            menu.mostrar()

        self.assertIn("DIAGNÓSTICO GENERAL", output.getvalue())
        self.assertIn("Estado: ⚠ ALERTA", output.getvalue())
        self.assertIn("Problemas encontrados: 1", output.getvalue())

    def test_all_guided_symptoms_have_a_diagnostic_route(self):
        self.assertEqual(
            {key for key, _label in GUIDED_OPTIONS},
            set(SUPPORTED_GUIDED_OPTIONS),
        )

    def test_guided_network_symptom_runs_automatic_network_diagnostic(self):
        network_diagnostic = Mock(return_value="network result")
        menu = DiagnosticsMenu(Mock(), network_diagnostic=network_diagnostic)
        with patch("builtins.input", return_value="5"):
            result = menu.mostrar(professional=True, guided=True)

        self.assertEqual(result, "network result")
        network_diagnostic.assert_called_once_with(True)

    def test_guided_audio_symptom_collects_audio_inventory(self):
        run = DiagnosticRun(
            timestamp="2026-09-27T12:00:00-06:00",
            mode="profesional",
            data={"processes": {"top_memory": []}},
            results=[
                DiagnosticResult(
                    code="SYSTEM_INFORMATION",
                    component="SISTEMA",
                    title="Información del sistema",
                    description="Disponible",
                    severity=Severity.NORMAL,
                ),
                DiagnosticResult(
                    code="GPU_DEVICE_STATUS",
                    component="GPU",
                    title="GPU",
                    description="Disponible",
                    severity=Severity.NORMAL,
                ),
            ],
        )
        menu = DiagnosticsMenu(Mock())
        with (
            patch("builtins.input", side_effect=("9", "0")),
            patch("ui.diagnostics.run_hardware_diagnostics", return_value=run),
            patch.object(
                HardwareInfo,
                "audio",
                return_value={"devices": [{"name": "Test audio device"}]},
            ),
            redirect_stdout(StringIO()),
        ):
            result = menu.mostrar(professional=True, guided=True)

        self.assertIn("audio", result.data)
        self.assertEqual(
            [finding.code for finding in result.results],
            ["GUIDED_AUDIO_INVENTORY"],
        )
        self.assertEqual(result.results[-1].severity, Severity.INFORMATION)

    def test_guided_audio_reports_windows_device_error_as_alert(self):
        run = DiagnosticRun(
            timestamp="2026-09-27T12:00:00-06:00",
            mode="profesional",
            data={},
            results=[],
        )
        menu = DiagnosticsMenu(Mock())
        with patch.object(
            HardwareInfo,
            "audio",
            return_value={"devices": [{"name": "Audio device", "status": "Error"}]},
        ):
            menu._add_device_inventory(run, "audio", "AUDIO")

        finding = run.results[0]
        self.assertEqual(finding.code, "GUIDED_AUDIO_DEVICE_STATUS")
        self.assertEqual(finding.severity, Severity.ALERT)
        self.assertIn("Audio device (Error)", _normal_evidence(finding.evidence))

    def test_guided_next_steps_are_specific_to_selected_symptom(self):
        output = StringIO()
        with redirect_stdout(output):
            DiagnosticsMenu._show_guided_next_steps("Se reinicia")

        self.assertIn("SIGUIENTES PASOS: SE REINICIA", output.getvalue())
        self.assertIn("pantallazo azul", output.getvalue())


if __name__ == "__main__":
    unittest.main()
