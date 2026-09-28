import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.severity import Severity
from modules.pruebas_avanzadas import (
    ADVANCED_TEST_THRESHOLDS,
    AdvancedDiagnostics,
    AdvancedDiagnosticRun,
    AdvancedTestResult,
)
from ui.pruebas_avanzadas import AdvancedTestsMenu


class FakeHardware:
    def __init__(self):
        self.cpu_data = {
            "model": "CPU Test",
            "physical_cores": 4,
            "threads": 8,
            "usage_percent": 5,
            "temperature_c": 50,
        }
        self.ram_data = {
            "total_bytes": 2 * 1024 ** 3,
            "available_bytes": 1024 ** 3,
            "used_bytes": 1024 ** 3,
            "percent": 50,
        }
        self.storage_data = {
            "volumes": [
                {
                    "mountpoint": "C:\\",
                    "free_bytes": 100 * 1024 ** 3,
                    "total_bytes": 500 * 1024 ** 3,
                }
            ],
            "physical_drives": [
                {"model": "Test SSD", "health": "normal", "temperature_c": 35, "status": "OK"}
            ],
        }

    def cpu(self):
        return dict(self.cpu_data)

    def gpu(self):
        return {
            "detected": True,
            "cards": [
                {
                    "name": "Test GPU",
                    "temperature_c": 40,
                    "usage_percent": 10,
                    "status": "OK",
                }
            ],
        }

    def battery(self):
        return {
            "detected": True,
            "design_capacity_mwh": 50000,
            "full_charge_capacity_mwh": 40000,
            "health_percent": 80,
            "cycle_count": 200,
            "temperature_c": None,
            "status": "OK",
        }

    def storage(self):
        return self.storage_data


class AdvancedDiagnosticsTests(unittest.TestCase):
    def test_cpu_test_stops_on_dangerous_temperature_and_emits_structured_finding(self):
        hardware = FakeHardware()
        diagnostic = AdvancedDiagnostics(hardware=hardware)
        with patch.object(
            diagnostic,
            "_sample_cpu",
            side_effect=lambda _start, _duration, _cancel, _stop, _usage, temps, _freq, _errors:
                temps.append(ADVANCED_TEST_THRESHOLDS["cpu_temperature_stop_c"]),
        ):
            result = diagnostic.cpu_test(duration_seconds=999)

        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertEqual(result.code, "ADVANCED_CPU_DANGEROUS_TEMPERATURE")
        self.assertEqual(result.measurements["duration_requested_seconds"], 15)
        serialized = result.to_dict()["diagnostic"]
        for field in (
            "code", "component", "title", "severity", "description", "evidence",
            "current_value", "expected_value", "recommendation", "confidence",
            "timestamp",
        ):
            self.assertIn(field, serialized)

    def test_cpu_test_supports_cancellation_and_duration_bounds(self):
        diagnostic = AdvancedDiagnostics(hardware=FakeHardware())
        cancel = threading.Event()
        cancel.set()
        result = diagnostic.cpu_test(duration_seconds=0, cancel_event=cancel)

        self.assertTrue(result.cancelled)
        self.assertEqual(result.measurements["duration_requested_seconds"], 1)
        self.assertEqual(result.severity, Severity.INFORMATION)

    def test_ram_test_verifies_limited_buffer_and_discloses_scope(self):
        diagnostic = AdvancedDiagnostics(hardware=FakeHardware())
        with patch(
            "modules.pruebas_avanzadas.psutil.virtual_memory",
            return_value=SimpleNamespace(
                total=2 * 1024 ** 3,
                available=512 * 1024 ** 2,
                used=1536 * 1024 ** 2,
                percent=75.0,
            ),
        ):
            result = diagnostic.ram_test()

        self.assertTrue(result.measurements["pattern_verified"])
        self.assertLessEqual(
            result.measurements["tested_bytes"],
            ADVANCED_TEST_THRESHOLDS["memory_test_max_bytes"],
        )
        self.assertIn("no sustituye", result.measurements["limitations"])

    def test_ram_test_reports_insufficient_memory_without_crashing(self):
        diagnostic = AdvancedDiagnostics(hardware=FakeHardware())
        with patch(
            "modules.pruebas_avanzadas.psutil.virtual_memory",
            return_value=SimpleNamespace(
                total=100, available=100, used=0, percent=0.0,
            ),
        ):
            result = diagnostic.ram_test()

        self.assertEqual(result.code, "ADVANCED_RAM_TEST_UNAVAILABLE")
        self.assertEqual(result.severity, Severity.INFORMATION)
        self.assertTrue(result.errors)

    def test_storage_test_detects_low_space_and_removes_only_its_temp_file(self):
        hardware = FakeHardware()
        hardware.storage_data["volumes"][0].update(
            free_bytes=10,
            total_bytes=100,
        )
        diagnostic = AdvancedDiagnostics(hardware=hardware)
        result = diagnostic.storage_test()

        self.assertEqual(result.code, "ADVANCED_STORAGE_LOW_SPACE")
        self.assertEqual(result.severity, Severity.ALERT)
        self.assertTrue(result.measurements["read_write_test"]["write_read_verified"])
        self.assertTrue(result.measurements["read_write_test"]["temporary_file_removed"])

    def test_storage_test_uses_critical_free_space_threshold(self):
        hardware = FakeHardware()
        hardware.storage_data["volumes"][0].update(
            free_bytes=4,
            total_bytes=100,
        )
        result = AdvancedDiagnostics(hardware=hardware).storage_test()

        self.assertEqual(result.code, "ADVANCED_STORAGE_CRITICAL_SPACE")
        self.assertEqual(result.severity, Severity.CRITICAL)

    def test_storage_test_reports_smart_failure_as_critical(self):
        hardware = FakeHardware()
        hardware.storage_data["physical_drives"][0]["health"] = "problem"
        result = AdvancedDiagnostics(hardware=hardware).storage_test()

        self.assertEqual(result.code, "ADVANCED_STORAGE_SMART_FAILURE")
        self.assertEqual(result.severity, Severity.CRITICAL)

    def test_gpu_without_device_is_informational(self):
        hardware = FakeHardware()
        hardware.gpu = lambda: {"detected": False, "cards": []}

        result = AdvancedDiagnostics(hardware=hardware).gpu_test()

        self.assertEqual(result.code, "ADVANCED_GPU_UNAVAILABLE")
        self.assertEqual(result.severity, Severity.INFORMATION)

    def test_gpu_temperature_is_evaluated_without_synthetic_load(self):
        hardware = FakeHardware()
        hardware.gpu = lambda: {
            "cards": [{
                "name": "Integrated GPU",
                "temperature_c": 90,
                "status": "OK",
            }]
        }
        result = AdvancedDiagnostics(hardware=hardware).gpu_test()

        self.assertEqual(result.severity, Severity.ALERT)
        self.assertIn("No se ejecutó carga sintética", result.measurements["load_test"])

    def test_gpu_critical_temperature_is_classified_critical(self):
        hardware = FakeHardware()
        hardware.gpu = lambda: {
            "cards": [{
                "name": "GPU caliente",
                "temperature_c": 100,
                "status": "OK",
            }]
        }

        result = AdvancedDiagnostics(hardware=hardware).gpu_test()

        self.assertEqual(result.code, "ADVANCED_GPU_CRITICAL_TEMPERATURE")
        self.assertEqual(result.severity, Severity.CRITICAL)

    def test_battery_wear_is_derived_and_absent_battery_is_not_failure(self):
        hardware = FakeHardware()
        hardware.battery = lambda: {
            "detected": True, "health_percent": 70,
            "design_capacity_mwh": 50000, "full_charge_capacity_mwh": 35000,
        }
        worn = AdvancedDiagnostics(hardware=hardware).battery_test()
        hardware.battery = lambda: {"detected": False}
        absent = AdvancedDiagnostics(hardware=hardware).battery_test()

        self.assertEqual(worn.measurements["wear_percent"], 30)
        self.assertEqual(worn.severity, Severity.ALERT)
        self.assertEqual(absent.severity, Severity.INFORMATION)
        self.assertEqual(absent.code, "ADVANCED_BATTERY_UNAVAILABLE")

    def test_network_test_reuses_existing_structured_network_diagnostic(self):
        network_result = SimpleNamespace(
            to_dict=lambda: {"checks": ["Adapter", "Gateway", "DNS", "Internet"]},
            severity=Severity.NORMAL,
            findings=[],
            diagnosis="CONECTIVIDAD NORMAL",
            recommendation="",
        )
        network = Mock()
        network.automatic_diagnostic.return_value = network_result

        result = AdvancedDiagnostics(
            hardware=FakeHardware(), network=network
        ).network_test()

        network.automatic_diagnostic.assert_called_once_with()
        self.assertEqual(result.measurements["checks"][2], "DNS")
        self.assertEqual(result.severity, Severity.NORMAL)

    def test_stability_test_observes_components_and_bounds_duration(self):
        class FakeClock:
            def __init__(self):
                self.now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = FakeClock()
        diagnostic = AdvancedDiagnostics(
            hardware=FakeHardware(),
            clock=clock.monotonic,
            sleeper=clock.sleep,
        )
        result = diagnostic.stability_test(999)

        self.assertEqual(result.measurements["duration_requested_seconds"], 120)
        self.assertGreaterEqual(result.measurements["sample_count"], 1)
        sample = result.measurements["samples"][0]
        self.assertIn("cpu_usage_percent", sample)
        self.assertIn("ram_usage_percent", sample)
        self.assertIn("cpu_temperature_c", sample)
        self.assertIn("gpu", sample)
        self.assertIn("disk_free_bytes", sample)

    def test_stability_stops_at_critical_temperature(self):
        hardware = FakeHardware()
        hardware.cpu_data["temperature_c"] = 100
        diagnostic = AdvancedDiagnostics(hardware=hardware)
        result = diagnostic.stability_test(10)

        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertEqual(result.code, "ADVANCED_STABILITY_TEMPERATURE_STOP")
        self.assertEqual(result.measurements["sample_count"], 1)

    def test_stability_reports_persistent_high_ram(self):
        class FakeClock:
            def __init__(self):
                self.now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = FakeClock()
        with patch(
            "modules.pruebas_avanzadas.psutil.virtual_memory",
            return_value=SimpleNamespace(
                total=100, available=5, used=95, percent=95,
            ),
        ), patch(
            "modules.pruebas_avanzadas.psutil.cpu_percent",
            return_value=20,
        ):
            result = AdvancedDiagnostics(
                hardware=FakeHardware(),
                clock=clock.monotonic,
                sleeper=clock.sleep,
            ).stability_test(10)

        self.assertEqual(result.code, "ADVANCED_STABILITY_HIGH_RAM")
        self.assertEqual(result.severity, Severity.ALERT)
        self.assertGreaterEqual(result.measurements["high_ram_samples"], 2)

    def test_complete_test_continues_after_individual_failure(self):
        diagnostic = AdvancedDiagnostics(hardware=FakeHardware())
        expected = [
            diagnostic._failed_test("CPU", RuntimeError("test error")),
            diagnostic._failed_test("RAM", RuntimeError("test error")),
            diagnostic._failed_test("ALMACENAMIENTO", RuntimeError("test error")),
            diagnostic._failed_test("GPU", RuntimeError("test error")),
            diagnostic._failed_test("BATERÍA", RuntimeError("test error")),
            diagnostic._failed_test("RED", RuntimeError("test error")),
        ]
        names = ("cpu_test", "ram_test", "storage_test", "gpu_test", "battery_test", "network_test")
        for name, result in zip(names, expected):
            setattr(diagnostic, name, Mock(return_value=result))

        run = diagnostic.complete_test()

        self.assertEqual(len(run.results), 6)
        self.assertEqual(run.severity, Severity.ALERT)
        self.assertTrue(all(isinstance(item, AdvancedTestResult) for item in run.results))
        self.assertEqual(len(run.to_dict()["results"]), 6)

    def test_complete_test_marks_cancelled_when_user_requests_it(self):
        diagnostic = AdvancedDiagnostics(hardware=FakeHardware())
        cancel = threading.Event()
        first = diagnostic._failed_test("CPU", RuntimeError("not used"))
        diagnostic.cpu_test = Mock(side_effect=lambda **_kwargs: (cancel.set(), first)[1])
        diagnostic.ram_test = Mock()
        run = diagnostic.complete_test(cancel_event=cancel)

        self.assertTrue(run.cancelled)
        self.assertEqual(len(run.results), 1)
        diagnostic.ram_test.assert_not_called()

    def test_menu_requires_opt_in_before_running_load_test(self):
        screens = Mock()
        diagnostics = Mock()
        menu = AdvancedTestsMenu(screens, diagnostics=diagnostics)
        with (
            patch("builtins.input", side_effect=("n", "")),
            patch("ui.pruebas_avanzadas.pausar"),
        ):
            menu._cpu(False)

        diagnostics.cpu_test.assert_not_called()


if __name__ == "__main__":
    unittest.main()
