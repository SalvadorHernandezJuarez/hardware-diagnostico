import io
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules.hardware import HardwareInfo
from ui.hardware import HardwareMenu


class HardwareInfoTests(unittest.TestCase):
    def test_complete_inventory_remains_available_when_windows_data_is_missing(self):
        with (
            patch.object(HardwareInfo, "_query", return_value=[]),
            patch("modules.hardware.CatalogoAmpliacion.detectar_equipo", return_value=None),
            patch("modules.hardware.psutil.sensors_battery", return_value=None),
        ):
            data = HardwareInfo().complete()

        self.assertEqual(
            set(data),
            {
                "system", "cpu", "ram", "storage", "gpu", "motherboard",
                "bios", "battery", "network", "overall_status",
            },
        )
        self.assertFalse(data["gpu"]["detected"])
        self.assertFalse(data["battery"]["detected"])
        self.assertEqual(data["ram"]["maximum_capacity"]["confidence"], "unknown")
        self.assertEqual(data["overall_status"]["components"]["gpu"], "unknown")

    def test_ram_keeps_smbios_capacity_and_module_data_structured(self):
        query_data = {
            "Win32_PhysicalMemory": [
                {
                    "Capacity": "8589934592",
                    "Manufacturer": "Example",
                    "PartNumber": "RAM-123",
                    "DeviceLocator": "DIMM 1",
                    "SMBIOSMemoryType": 26,
                    "Speed": 3200,
                }
            ],
            "Win32_PhysicalMemoryArray": [
                {"MaxCapacity": 33554432, "MemoryDevices": 4}
            ],
        }
        with patch.object(
            HardwareInfo, "_query", side_effect=lambda name, **_kwargs: query_data.get(name, [])
        ):
            data = HardwareInfo().ram()

        self.assertEqual(data["modules"][0]["capacity_gb"], 8)
        self.assertEqual(data["modules"][0]["memory_type"], "DDR4")
        self.assertEqual(data["installed_gb"], 8)
        self.assertEqual(data["free_slots"], 3)
        self.assertEqual(data["maximum_capacity"]["capacity_gb"], 32)
        self.assertEqual(
            data["maximum_capacity"]["confidence"], "reported_by_smbios"
        )

    def test_expansion_does_not_claim_undetected_m2_slots(self):
        query_data = {
            "Win32_DiskDrive": [
                {
                    "Model": "NVMe test",
                    "PNPDeviceID": "NVME\\TEST",
                    "InterfaceType": "SCSI",
                    "Size": 512 * 1024 ** 3,
                }
            ],
        }
        with (
            patch.object(
                HardwareInfo, "_query",
                side_effect=lambda name, **_kwargs: query_data.get(name, []),
            ),
            patch(
                "modules.hardware.CatalogoAmpliacion.detectar_equipo",
                return_value=None,
            ),
        ):
            data = HardwareInfo().expansion()

        self.assertEqual(data["storage"]["nvme_devices_detected"], 1)
        self.assertIsNone(data["storage"]["m2_slots_detected"])
        self.assertIsNone(data["storage"]["free_slots"])
        self.assertEqual(data["storage"]["expansion_possible"], "unknown")

    def test_missing_wmi_and_powershell_returns_empty_data_and_logs(self):
        with (
            patch.dict(sys.modules, {"wmi": None}),
            patch("modules.hardware.shutil.which", return_value=None),
            self.assertLogs("hardware_diagnostico", level="WARNING"),
        ):
            self.assertEqual(HardwareInfo()._query("Win32_Processor"), [])

    def test_audio_does_not_claim_playback_or_recording_direction(self):
        with patch.object(HardwareInfo, "_query", return_value=[]):
            data = HardwareInfo().audio()

        self.assertIsNone(data["playback_devices"])
        self.assertIsNone(data["recording_devices"])
        self.assertEqual(data["devices"], [])

    def test_storage_links_logical_volume_to_physical_drive_when_wmi_reports_it(self):
        queries = {
            "Win32_DiskDrive": [
                {
                    "Model": "Example SSD",
                    "DeviceID": r"\\.\PHYSICALDRIVE0",
                    "Size": 100 * 1024 ** 3,
                }
            ],
            "Win32_DiskDriveToDiskPartition": [
                {
                    "Antecedent": 'Win32_DiskDrive.DeviceID="\\\\\\\\.\\\\PHYSICALDRIVE0"',
                    "Dependent": 'Win32_DiskPartition.DeviceID="Disk #0, Partition #1"',
                }
            ],
            "Win32_LogicalDiskToPartition": [
                {
                    "Antecedent": 'Win32_DiskPartition.DeviceID="Disk #0, Partition #1"',
                    "Dependent": 'Win32_LogicalDisk.DeviceID="C:"',
                }
            ],
        }
        partition = SimpleNamespace(device="C:\\", mountpoint="C:\\", fstype="NTFS")
        usage = SimpleNamespace(
            total=100 * 1024 ** 3,
            used=40 * 1024 ** 3,
            free=60 * 1024 ** 3,
            percent=40,
        )
        with (
            patch.object(
                HardwareInfo, "_query",
                side_effect=lambda name, **_kwargs: queries.get(name, []),
            ),
            patch("modules.hardware.psutil.disk_partitions", return_value=[partition]),
            patch("modules.hardware.psutil.disk_usage", return_value=usage),
        ):
            data = HardwareInfo().storage()

        self.assertEqual(data["volumes"][0]["physical_drive_index"], 0)
        self.assertEqual(data["volumes"][0]["physical_drive_model"], "Example SSD")


class HardwareMenuTests(unittest.TestCase):
    def test_all_hardware_options_route_to_structured_module_functions(self):
        screens = Mock()
        collector = Mock()
        for _title, method_name in HardwareMenu.OPTIONS.values():
            getattr(collector, method_name).return_value = {}
        menu = HardwareMenu(screens)
        with (
            patch("ui.hardware.HardwareInfo", return_value=collector),
            patch("ui.hardware.pausar"),
            patch("builtins.input", side_effect=[*HardwareMenu.OPTIONS, "0"]),
            redirect_stdout(io.StringIO()),
        ):
            menu.mostrar()

        for _title, method_name in HardwareMenu.OPTIONS.values():
            getattr(collector, method_name).assert_called_once_with()

    def test_professional_view_includes_identifiers_hidden_in_normal_mode(self):
        menu = HardwareMenu(Mock())
        data = {"model": "CPU", "processor_id": "ID-123"}
        normal = io.StringIO()
        technical = io.StringIO()
        with redirect_stdout(normal):
            menu._show_fields(data, ("model", "processor_id"), False)
        with redirect_stdout(technical):
            menu._show_fields(data, ("model", "processor_id"), True)

        self.assertNotIn("ID-123", normal.getvalue())
        self.assertIn("ID-123", technical.getvalue())


if __name__ == "__main__":
    unittest.main()
