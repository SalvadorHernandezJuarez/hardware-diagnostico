import os
import unittest
from unittest.mock import Mock, patch

from core.severity import Severity
from modules.herramientas_sistema import (
    ADMIN_TOOLS,
    DIAGNOSTIC_COMMANDS,
    SystemToolsDiagnostics,
    _run,
)
from ui.herramientas_sistema import SystemToolsMenu
from modules.red import NetworkAdapter, NetworkConfiguration


class SystemToolsDiagnosticsTests(unittest.TestCase):
    def test_windows_information_contains_available_system_fields(self):
        query = Mock(return_value=[{
            "Edition": "Windows Test",
            "Version": "10.0",
            "Build": "12345",
            "Architecture": "64-bit",
            "InstallDate": "2025-01-01",
            "LastBootUpTime": "2025-02-01",
        }])
        with patch("modules.herramientas_sistema.psutil.boot_time", return_value=1000):
            report = SystemToolsDiagnostics(powershell_query=query).windows_info()

        self.assertEqual(report.data["edition"], "Windows Test")
        self.assertEqual(report.data["build"], "12345")
        self.assertEqual(report.data["install_date"], "2025-01-01")
        self.assertGreaterEqual(report.data["uptime_seconds"], 0)
        self.assertEqual(report.finding.code, "SYSTEM_TOOLS_WINDOWS_INFO")
        self.assertIn("component", report.to_dict())
        self.assertIn("confidence", report.to_dict())

    def test_windows_information_survives_power_shell_permission_failure(self):
        with (
            patch("modules.herramientas_sistema.psutil.boot_time", side_effect=PermissionError),
        ):
            report = SystemToolsDiagnostics(
                powershell_query=lambda _script: (_ for _ in ()).throw(
                    PermissionError("Access denied")
                )
            ).windows_info()

        self.assertEqual(report.data["edition"], "DESCONOCIDO")
        self.assertIn("Access denied", report.data["query_error"])
        self.assertEqual(report.finding.severity, Severity.INFORMATION)

    def test_system_tools_menu_requires_professional_mode(self):
        menu = SystemToolsMenu(Mock())
        with (
            patch("ui.herramientas_sistema.pausar"),
            patch.object(menu.diagnostics, "windows_info") as windows_info,
            patch("builtins.print") as printer,
        ):
            menu.mostrar(professional=False)

        windows_info.assert_not_called()
        self.assertIn(
            "solo están disponibles en Modo Profesional.",
            printer.call_args.args[0],
        )

    def test_admin_tools_are_only_listed_in_professional_mode(self):
        with patch("builtins.print") as printer:
            SystemToolsMenu._menu(professional=False)
        normal_output = " ".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertNotIn("Consola administrativa", normal_output)

        with patch("builtins.print") as printer:
            SystemToolsMenu._menu(professional=True)
        professional_output = " ".join(
            str(call.args[0]) for call in printer.call_args_list
        )
        self.assertIn("[10] Consola administrativa", professional_output)

    def test_environment_variables_supports_allowlisted_and_specific_lookup(self):
        with patch.dict(os.environ, {"PATH": "C:\\Windows", "CUSTOM_DIAG": "value"}):
            diagnostics = SystemToolsDiagnostics()
            common = diagnostics.environment_variables()
            selected = diagnostics.environment_variables("custom_diag")

        self.assertEqual(common.data["variables"]["PATH"], "C:\\Windows")
        self.assertEqual(selected.data["variables"]["CUSTOM_DIAG"], "value")
        invalid = diagnostics.environment_variables("BAD;NAME")
        self.assertIn("error", invalid.data)

    def test_processes_are_delegated_and_sorted_by_requested_metric(self):
        maintenance = Mock()
        maintenance.list_processes.return_value = [
            {"pid": 1, "cpu_percent": 2.0, "memory_bytes": 300},
            {"pid": 2, "cpu_percent": 80.0, "memory_bytes": 100},
        ]
        diagnostics = SystemToolsDiagnostics(maintenance=maintenance)

        cpu = diagnostics.processes("cpu")
        memory = diagnostics.processes("memory")

        self.assertEqual([row["pid"] for row in cpu.data["processes"]], [2, 1])
        self.assertEqual([row["pid"] for row in memory.data["processes"]], [1, 2])
        maintenance.list_processes.assert_called()

    def test_all_services_are_delegated_to_maintenance(self):
        maintenance = Mock()
        maintenance.services_info.return_value = [{"Name": "Spooler", "State": "Running"}]
        result = SystemToolsDiagnostics(maintenance=maintenance).services()

        self.assertEqual(result.data["services"][0]["Name"], "Spooler")
        maintenance.services_info.assert_called_once_with(all_services=True)

    def test_driver_and_device_queries_report_unknown_status_without_fabrication(self):
        def query(script):
            if "Win32_PnPSignedDriver" in script:
                return [{"DeviceName": "Audio", "Manufacturer": None}]
            return [
                {"Name": "Audio", "Status": "OK", "ConfigManagerErrorCode": 0},
                {"Name": "Degraded provider", "Status": "Degraded", "ConfigManagerErrorCode": 0},
                {"Name": "Unknown device", "Status": "Error", "ConfigManagerErrorCode": 28},
            ]

        diagnostics = SystemToolsDiagnostics(powershell_query=query)
        drivers = diagnostics.drivers()
        devices = diagnostics.devices()

        self.assertIsNone(drivers.data["drivers"][0]["Manufacturer"])
        self.assertEqual(devices.finding.severity, Severity.ALERT)
        self.assertEqual(len(devices.findings) - 1, 1)
        self.assertEqual(devices.findings[1].code, "SYSTEM_TOOLS_DEVICE_PROBLEM")
        self.assertEqual(devices.findings[1].current_value["code"], 28)

    def test_driver_query_failure_is_reported_as_unavailable(self):
        report = SystemToolsDiagnostics(
            powershell_query=lambda _script: None
        ).drivers()

        self.assertFalse(report.data["available"])
        self.assertIn("error", report.data)
        self.assertEqual(report.finding.severity, Severity.INFORMATION)

    def test_network_information_reuses_network_module_structure(self):
        configuration = NetworkConfiguration(
            hostname="host",
            adapters=[
                NetworkAdapter(
                    name="Ethernet",
                    adapter_type="Ethernet",
                    status="Conectado",
                    ipv4=["192.0.2.5"],
                    gateways=["192.0.2.1"],
                    dns_servers=["192.0.2.53"],
                )
            ],
            default_gateway="192.0.2.1",
            dns_servers=["192.0.2.53"],
            apipa_addresses=[],
            valid_ipv4=True,
        )
        network = Mock()
        network.get_configuration.return_value = configuration
        report = SystemToolsDiagnostics(network=network).network_info()

        network.get_configuration.assert_called_once_with()
        adapter = report.data["adapters"][0]
        self.assertEqual(adapter["ipv4"], ["192.0.2.5"])
        self.assertEqual(adapter["mac"], "DESCONOCIDO")

    def test_recent_events_are_read_only_and_structured(self):
        rows = [{"Date": "2026-01-01", "Id": 41, "ProviderName": "Disk"}]
        report = SystemToolsDiagnostics(
            powershell_query=lambda _script: rows
        ).recent_events()

        self.assertEqual(report.data["events"], rows)
        self.assertIn("Get-WinEvent", report.source)

    def test_diagnostic_command_uses_only_fixed_arguments_and_captures_metadata(self):
        runner = Mock(return_value={
            "return_code": 0,
            "stdout": "output",
            "stderr": "",
            "error": None,
            "duration_seconds": 1.25,
        })
        diagnostics = SystemToolsDiagnostics(command_runner=runner)

        result = diagnostics.run_diagnostic_command("ipconfig")
        rejected = diagnostics.run_diagnostic_command("ipconfig & whoami")

        self.assertEqual(result["stdout"], "output")
        self.assertEqual(result["return_code"], 0)
        self.assertEqual(result["duration_seconds"], 1.25)
        self.assertEqual(runner.call_args.args[0], DIAGNOSTIC_COMMANDS["ipconfig"]["command"])
        self.assertFalse(rejected["success"])
        self.assertEqual(runner.call_count, 1)

    def test_diagnostic_command_surfaces_access_denied(self):
        runner = Mock(return_value={
            "return_code": None,
            "stdout": "",
            "stderr": "Access denied",
            "error": "Permission denied",
            "duration_seconds": 0.01,
        })
        result = SystemToolsDiagnostics(command_runner=runner).run_diagnostic_command("sfc")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Permission denied")
        self.assertIn("Access denied", result["stderr"])
        self.assertEqual(runner.call_args.kwargs["timeout"], 120)

    def test_admin_tools_require_professional_mode_and_explicit_confirmation(self):
        launcher = Mock()
        diagnostics = SystemToolsDiagnostics(launcher=launcher)
        with patch("modules.herramientas_sistema.os.name", "nt"):
            normal = diagnostics.launch_admin_tool(
                "services", professional=False, confirm_token="CONFIRMAR"
            )
            unconfirmed = diagnostics.launch_admin_tool(
                "services", professional=True, confirm_token=""
            )
            invalid = diagnostics.launch_admin_tool(
                "cmd", professional=True, confirm_token="CONFIRMAR"
            )

        self.assertFalse(normal["success"])
        self.assertFalse(unconfirmed["success"])
        self.assertFalse(invalid["success"])
        launcher.assert_not_called()

    def test_confirmed_admin_tool_launches_only_predefined_program(self):
        launcher = Mock()
        diagnostics = SystemToolsDiagnostics(launcher=launcher)
        with (
            patch("modules.herramientas_sistema.os.name", "nt"),
            patch("modules.herramientas_sistema.registrar_accion") as log_action,
        ):
            result = diagnostics.launch_admin_tool(
                "devices", professional=True, confirm_token="CONFIRMAR"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["command"], ADMIN_TOOLS["devices"][1])
        launcher.assert_called_once()
        self.assertIs(launcher.call_args.kwargs["shell"], False)
        log_action.assert_called_once()

    def test_subprocess_permission_error_is_returned_not_raised(self):
        with patch(
            "modules.herramientas_sistema.subprocess.run",
            side_effect=PermissionError("Access denied"),
        ):
            result = _run(["sfc", "/verifyonly"], timeout=1)

        self.assertIsNone(result["return_code"])
        self.assertIn("Access denied", result["error"])


if __name__ == "__main__":
    unittest.main()
