import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.severity import Severity
from modules.mantenimiento import (
    CONFIRMATION_TOKEN,
    CRITICAL_PROCESS_NAMES,
    MaintenanceDiagnostics,
    MaintenanceActionResult,
    MaintenanceCheck,
    MaintenanceAuditResult,
)
from ui.mantenimiento import MaintenanceMenu


class MaintenanceActionTests(unittest.TestCase):
    def test_process_action_requires_explicit_confirmation_before_touching_process(self):
        with patch("modules.mantenimiento.psutil.Process") as process:
            result = MaintenanceDiagnostics().terminate_process(123, "")

        self.assertFalse(result.success)
        self.assertIn("CONFIRMAR", result.error)
        process.assert_not_called()

    def test_critical_processes_are_protected_even_after_confirmation(self):
        name = next(iter(CRITICAL_PROCESS_NAMES))
        process = Mock()
        process.name.return_value = name
        with patch("modules.mantenimiento.psutil.Process", return_value=process):
            result = MaintenanceDiagnostics().terminate_process(
                123, CONFIRMATION_TOKEN
            )

        self.assertEqual(result.result, "Bloqueado")
        process.terminate.assert_not_called()

    def test_windows_system_pid_is_protected_independent_of_process_name(self):
        with patch("modules.mantenimiento.psutil.Process") as process:
            result = MaintenanceDiagnostics().terminate_process(
                4, CONFIRMATION_TOKEN
            )
        self.assertEqual(result.result, "Bloqueado")
        process.assert_not_called()

    def test_confirmed_process_action_terminates_and_records_context(self):
        process = Mock()
        process.name.return_value = "example.exe"
        with patch("modules.mantenimiento.psutil.Process", return_value=process):
            result = MaintenanceDiagnostics().terminate_process(
                456, CONFIRMATION_TOKEN
            )

        self.assertTrue(result.success)
        self.assertEqual(result.target, 456)
        self.assertTrue(result.computer)
        self.assertTrue(result.user)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    def test_access_denied_process_action_returns_clear_error(self):
        process = Mock()
        process.name.return_value = "example.exe"
        process.terminate.side_effect = __import__("psutil").AccessDenied(123)
        with patch("modules.mantenimiento.psutil.Process", return_value=process):
            result = MaintenanceDiagnostics().terminate_process(
                123, CONFIRMATION_TOKEN
            )
        self.assertFalse(result.success)
        self.assertEqual(result.result, "Permiso denegado")

    def test_service_actions_require_confirmation_professional_mode_and_allowlist(self):
        diagnostics = MaintenanceDiagnostics(command_runner=Mock())

        no_confirmation = diagnostics.change_service(
            "Spooler", "stop", "", professional=True
        )
        not_professional = diagnostics.change_service(
            "Spooler", "stop", CONFIRMATION_TOKEN, professional=False
        )
        restart_not_professional = diagnostics.change_service(
            "Spooler", "restart", CONFIRMATION_TOKEN, professional=False
        )
        critical = diagnostics.change_service(
            "MpsSvc", "stop", CONFIRMATION_TOKEN, professional=True
        )

        self.assertFalse(no_confirmation.success)
        self.assertFalse(not_professional.success)
        self.assertFalse(restart_not_professional.success)
        self.assertEqual(restart_not_professional.risk, "CONFIRMACIÓN")
        self.assertEqual(critical.result, "Bloqueado")
        diagnostics._run.assert_not_called()

    def test_service_success_runs_native_command_and_logs_risk(self):
        runner = Mock(return_value={"return_code": 0, "stdout": "OK", "stderr": ""})
        with (
            patch("modules.mantenimiento.os.name", "nt"),
            patch("modules.mantenimiento.shutil.which", return_value="sc.exe"),
        ):
            result = MaintenanceDiagnostics(command_runner=runner).change_service(
                "Spooler",
                "stop",
                CONFIRMATION_TOKEN,
                professional=True,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.risk, "PROFESIONAL")
        self.assertEqual(runner.call_args.args[0][1:], ["stop", "Spooler"])

    def test_recycle_bin_requires_confirmation_before_running_command(self):
        runner = Mock()
        diagnostics = MaintenanceDiagnostics(command_runner=runner)
        with patch("modules.mantenimiento.os.name", "nt"):
            result = diagnostics.empty_recycle_bin("")
        self.assertFalse(result.success)
        runner.assert_not_called()

    def test_confirmed_service_restart_records_confirmation_risk(self):
        runner = Mock(
            return_value={"return_code": 0, "stdout": "OK", "stderr": ""}
        )
        with (
            patch("modules.mantenimiento.os.name", "nt"),
            patch("modules.mantenimiento.shutil.which", return_value="sc.exe"),
            patch("modules.mantenimiento.time.sleep"),
        ):
            result = MaintenanceDiagnostics(command_runner=runner).change_service(
                "Spooler", "restart", CONFIRMATION_TOKEN, professional=True
            )
        self.assertTrue(result.success)
        self.assertEqual(result.risk, "CONFIRMACIÓN")
        self.assertEqual(runner.call_count, 2)


class MaintenanceReadTests(unittest.TestCase):
    def test_temporary_inventory_counts_files_in_allowed_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.tmp").write_bytes(b"x" * 50)
            (root / "two.tmp").write_bytes(b"y" * 70)
            with (
                patch("modules.mantenimiento.tempfile.gettempdir", return_value=directory),
                patch.dict(os.environ, {"WINDIR": str(root / "Windows")}),
            ):
                result = MaintenanceDiagnostics().temporary_inventory()

        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["size_bytes"], 120)
        self.assertEqual(len(result["locations"]), 1)

    def test_temporary_cleanup_requires_confirmation_and_only_removes_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "safe.tmp"
            target.write_text("temporary", encoding="utf-8")
            old_time = os.path.getmtime(target) - 2 * 24 * 60 * 60
            os.utime(target, (old_time, old_time))
            diagnostics = MaintenanceDiagnostics()
            with (
                patch("modules.mantenimiento.tempfile.gettempdir", return_value=directory),
                patch.dict(os.environ, {"WINDIR": str(root / "Windows")}),
            ):
                denied = diagnostics.delete_temporary_files("")
                self.assertTrue(target.exists())
                allowed = diagnostics.delete_temporary_files(CONFIRMATION_TOKEN)

        self.assertFalse(denied.success)
        self.assertTrue(allowed.success)
        self.assertEqual(allowed.details["deleted_count"], 1)
        self.assertFalse(target.exists())

    def test_temporary_cleanup_keeps_recent_files_even_with_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "recent.tmp"
            target.write_text("active", encoding="utf-8")
            with (
                patch("modules.mantenimiento.tempfile.gettempdir", return_value=directory),
                patch.dict(os.environ, {"WINDIR": str(root / "Windows")}),
            ):
                inventory = MaintenanceDiagnostics().temporary_inventory()
                result = MaintenanceDiagnostics().delete_temporary_files(
                    CONFIRMATION_TOKEN
                )
                self.assertTrue(target.exists())
        self.assertEqual(inventory["eligible_file_count"], 0)
        self.assertEqual(result.details["deleted_count"], 0)

    def test_startup_folder_disable_and_restore_are_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            appdata = Path(directory) / "AppData"
            startup = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup.mkdir(parents=True)
            item_path = startup / "app.lnk"
            item_path.write_text("shortcut", encoding="utf-8")
            with patch(
                "modules.mantenimiento._startup_folders",
                return_value=[startup],
            ), patch("modules.mantenimiento._registry_startup_items", return_value=[]), patch.dict(
                os.environ,
                {"APPDATA": str(appdata), "USERPROFILE": str(Path.home())},
            ):
                diagnostics = MaintenanceDiagnostics()
                original = diagnostics.startup_items()[0]
                denied = diagnostics.disable_startup_item(original["id"], "")
                self.assertTrue(item_path.exists())
                disabled = diagnostics.disable_startup_item(
                    original["id"], CONFIRMATION_TOKEN
                )
                listed = diagnostics.startup_items(include_disabled=True)
                disabled_item = listed[0]
                restored = diagnostics.restore_startup_item(
                    disabled_item["id"], CONFIRMATION_TOKEN
                )
                self.assertTrue(disabled.success)
                self.assertTrue(restored.success)
                self.assertEqual(
                    {path.name for path in startup.iterdir()},
                    {"app.lnk"},
                )

        self.assertFalse(denied.success)

    def test_startup_machine_folder_requires_admin_and_is_not_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            program_data = Path(directory) / "ProgramData"
            startup = program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup.mkdir(parents=True)
            item_path = startup / "app.lnk"
            item_path.write_text("shortcut", encoding="utf-8")
            with (
                patch("modules.mantenimiento._startup_folders", return_value=[startup]),
                patch("modules.mantenimiento._registry_startup_items", return_value=[]),
                patch.dict(os.environ, {"PROGRAMDATA": str(program_data)}),
            ):
                diagnostics = MaintenanceDiagnostics()
                item = diagnostics.startup_items()[0]
                result = diagnostics.disable_startup_item(item["id"], CONFIRMATION_TOKEN)
                self.assertTrue(item_path.exists())
        self.assertFalse(result.success)

    def test_machine_registry_startup_changes_require_professional_mode(self):
        item = {
            "id": "registry:HKLM:Run:Vendor",
            "name": "Vendor",
            "enabled": True,
            "origin": "HKLM\\Run",
            "command": "vendor.exe",
            "kind": "registry",
            "scope": "machine",
            "registry_hive": "HKLM",
            "registry_key": "Run",
            "value_name": "Vendor",
            "data_type": 1,
        }
        diagnostics = MaintenanceDiagnostics()
        with (
            patch.object(diagnostics, "startup_items", return_value=[item]),
            patch("modules.mantenimiento._disable_registry_startup") as disable,
        ):
            denied = diagnostics.disable_startup_item(
                item["id"], CONFIRMATION_TOKEN, professional=False
            )
            self.assertEqual(denied.risk, "PROFESIONAL")
            disable.assert_not_called()

            allowed = diagnostics.disable_startup_item(
                item["id"], CONFIRMATION_TOKEN, professional=True
            )

        self.assertTrue(allowed.success)
        self.assertEqual(allowed.risk, "PROFESIONAL")
        disable.assert_called_once_with(item)

    def test_memory_inventory_does_not_claim_memory_can_be_increased(self):
        diagnostics = MaintenanceDiagnostics()
        with (
            patch("modules.mantenimiento.psutil.virtual_memory") as virtual_memory,
            patch.object(diagnostics, "list_processes", return_value=[]),
        ):
            virtual_memory.return_value = SimpleNamespace(
                total=16 * 1024 ** 3,
                available=8 * 1024 ** 3,
                used=8 * 1024 ** 3,
                percent=50,
            )
            result = diagnostics.release_memory()
        self.assertIn("No se modifica ni aumenta la RAM", result["message"])

    def test_recommended_maintenance_emits_structured_ram_and_storage_findings(self):
        diagnostics = MaintenanceDiagnostics()
        diagnostics.memory_info = Mock(return_value={
            "usage_percent": 92.0,
            "total_gb": 16,
            "available_gb": 1.2,
            "used_gb": 14.8,
            "top_processes": [{"name": "app.exe", "memory_mb": 512}],
        })
        diagnostics.storage_info = Mock(return_value=[{
            "mountpoint": "C:\\",
            "used_percent": 92,
            "free_gb": 8,
            "total_gb": 100,
        }])
        diagnostics.temporary_inventory = Mock(return_value={
            "locations": [], "file_count": 0, "size_bytes": 0,
            "size_mb": 0, "files": [], "errors": [],
        })
        diagnostics.recycle_bin_inventory = Mock(return_value={
            "available": True, "count": 0, "size_bytes": 0,
            "size_mb": 0, "error": None,
        })
        diagnostics.startup_items = Mock(return_value=[])
        diagnostics.services_info = Mock(return_value=[])

        result = diagnostics.recommended_maintenance()

        self.assertIsInstance(result, MaintenanceAuditResult)
        codes = [item.code for item in result.recommendations]
        self.assertIn("MAINTENANCE_RAM_HIGH", codes)
        self.assertIn("MAINTENANCE_DISK_LOW_SPACE", codes)
        self.assertEqual(result.severity, Severity.ALERT)
        self.assertIsInstance(result.checks[0], MaintenanceCheck)

    def test_recommended_audit_only_inspects_and_does_not_perform_actions(self):
        diagnostics = MaintenanceDiagnostics()
        diagnostics.memory_info = Mock(return_value={
            "usage_percent": 30.0, "total_gb": 8, "available_gb": 5,
            "used_gb": 3, "top_processes": [],
        })
        diagnostics.storage_info = Mock(return_value=[])
        diagnostics.temporary_inventory = Mock(return_value={
            "locations": [], "file_count": 0, "size_bytes": 0,
            "size_mb": 0, "files": [], "errors": [],
        })
        diagnostics.recycle_bin_inventory = Mock(return_value={
            "available": False, "count": None, "size_bytes": None,
            "size_mb": None, "error": "No disponible",
        })
        diagnostics.startup_items = Mock(return_value=[])
        diagnostics.services_info = Mock(return_value=[])
        diagnostics.terminate_process = Mock()
        diagnostics.delete_temporary_files = Mock()
        diagnostics.empty_recycle_bin = Mock()

        diagnostics.recommended_maintenance()

        diagnostics.terminate_process.assert_not_called()
        diagnostics.delete_temporary_files.assert_not_called()
        diagnostics.empty_recycle_bin.assert_not_called()

    def test_recommended_audit_continues_when_an_inventory_raises(self):
        diagnostics = MaintenanceDiagnostics()
        diagnostics.memory_info = Mock(side_effect=PermissionError("denied"))
        diagnostics.storage_info = Mock(return_value=[])
        diagnostics.temporary_inventory = Mock(return_value={
            "locations": [], "file_count": 0, "size_bytes": 0,
            "size_mb": 0, "eligible_file_count": 0,
            "eligible_size_bytes": 0, "eligible_size_mb": 0,
            "truncated": False, "files": [], "errors": [],
        })
        diagnostics.recycle_bin_inventory = Mock(return_value={
            "available": False, "count": None, "size_bytes": None,
            "size_mb": None, "error": "No disponible",
        })
        diagnostics.startup_items = Mock(return_value=[])
        diagnostics.services_info = Mock(return_value=[])

        result = diagnostics.recommended_maintenance()

        self.assertIn(
            "MAINTENANCE_RAM_UNAVAILABLE",
            [finding.code for finding in result.findings],
        )
        self.assertIn(
            "MAINTENANCE_PAPELERA_UNAVAILABLE",
            [finding.code for finding in result.findings],
        )


class MaintenanceMenuTests(unittest.TestCase):
    def test_menu_exposes_all_maintenance_features(self):
        with patch("builtins.print") as printer:
            MaintenanceMenu._menu()
        output = " ".join(
            str(call.args[0]) for call in printer.call_args_list
        )
        self.assertIn("[8] Mantenimiento recomendado", output)
        self.assertIn("[0] Volver", output)

    def test_service_actions_are_labeled_as_professional_only(self):
        with patch("builtins.print") as printer:
            MaintenanceMenu._menu(professional=False)
        normal_output = " ".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("Servicios (solo lectura)", normal_output)

        with patch("builtins.print") as printer:
            MaintenanceMenu._menu(professional=True)
        professional_output = " ".join(
            str(call.args[0]) for call in printer.call_args_list
        )
        self.assertIn("Servicios y acciones profesionales", professional_output)

    def test_normal_startup_menu_does_not_offer_machine_scope_changes(self):
        menu = MaintenanceMenu(Mock())
        menu.diagnostics.startup_items = Mock(return_value=[{
            "id": "registry:HKLM:Run:Vendor",
            "name": "Vendor",
            "enabled": True,
            "scope": "machine",
            "origin": "Registry",
            "command": "vendor.exe",
        }])
        menu.diagnostics.disable_startup_item = Mock()
        output = StringIO()
        with (
            patch("builtins.input", return_value="1"),
            patch("ui.mantenimiento.pausar"),
            redirect_stdout(output),
        ):
            menu._show_startup(professional=False)

        menu.diagnostics.disable_startup_item.assert_not_called()
        self.assertIn("solo Modo Profesional para modificar", output.getvalue())
        self.assertIn("solo se puede modificar en Modo Profesional", output.getvalue())

    def test_service_start_confirmation_is_not_bypassed_by_ui(self):
        screens = Mock()
        menu = MaintenanceMenu(screens)
        menu.diagnostics.services_info = Mock(return_value=[{
            "Name": "Spooler", "DisplayName": "Print Spooler",
            "State": "Stopped", "StartMode": "Manual",
        }])
        menu.diagnostics.change_service = Mock()
        with (
            patch("builtins.input", side_effect=["1", "n", ""]),
            patch("ui.mantenimiento.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu._show_services(professional=True)
        menu.diagnostics.change_service.assert_not_called()

    def test_memory_view_allows_only_explicitly_confirmed_process_choice(self):
        screens = Mock()
        menu = MaintenanceMenu(screens)
        menu.diagnostics.memory_info = Mock(return_value={
            "total_gb": 8,
            "available_gb": 4,
            "used_gb": 4,
            "usage_percent": 50,
            "top_processes": [{
                "pid": 101,
                "name": "app.exe",
                "cpu_percent": 1,
                "memory_mb": 100,
                "memory_percent": 2,
                "user": "user",
                "status": "running",
            }],
        })
        action = MaintenanceActionResult(
            action="finalizar proceso",
            success=True,
            computer="test",
            user="user",
            timestamp="timestamp",
            target=101,
            result="Finalizado",
        )
        menu.diagnostics.terminate_process = Mock(return_value=action)
        with (
            patch("builtins.input", side_effect=["1", "CONFIRMAR", ""]),
            patch("ui.mantenimiento.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu._show_memory(professional=False)
        menu.diagnostics.terminate_process.assert_called_once_with(101, "CONFIRMAR")


if __name__ == "__main__":
    unittest.main()
