"""Structured, read-only hardware inventory for Windows."""

import json
import logging
import platform
import re
import shutil
import sqlite3
import subprocess
import time

import psutil

from utils.ampliacion_hardware import CatalogoAmpliacion


logger = logging.getLogger("hardware_diagnostico")

RAM_TYPES = {
    0: "Desconocido",
    20: "DDR",
    21: "DDR2",
    24: "DDR3",
    26: "DDR4",
    34: "DDR5",
}


def _value(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    try:
        return getattr(item, name, default)
    except Exception:
        return default


def _text(value):
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _gb(value):
    number = _integer(value)
    return round(number / (1024 ** 3), 2) if number is not None else None


def _dmtf_date(value):
    raw = _text(value)
    if raw and re.match(r"^\d{14}\.\d{6}[+-]\d{3}$", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


class HardwareInfo:
    """Collects hardware information as JSON-compatible dictionaries.

    Each public method returns a section with stable snake_case keys. Missing
    fields are ``None``; presentation and future diagnostic rules can therefore
    consume the same data without parsing terminal output.
    """

    def __init__(self):
        self._cache = {}
        self._wmi_connections = {}
        self._wmi_unavailable_logged = False

    def _query(self, class_name, namespace=r"root\cimv2"):
        cache_key = (namespace, class_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        values = None
        try:
            import wmi

            connection = self._wmi_connections.get(namespace)
            if connection is None:
                connection = wmi.WMI(namespace=namespace)
                self._wmi_connections[namespace] = connection
            values = list(getattr(connection, class_name)())
        except ImportError:
            values = self._query_powershell(class_name, namespace)
        except Exception:
            logger.warning(
                "No se pudo consultar WMI: %s (%s)", class_name, namespace,
                exc_info=True,
            )
            values = self._query_powershell(class_name, namespace)

        if values is None and not self._wmi_unavailable_logged:
            logger.warning(
                "WMI no está disponible y no se pudo consultar CIM mediante PowerShell."
            )
            self._wmi_unavailable_logged = True
        result = values or []
        self._cache[cache_key] = result
        return result

    @staticmethod
    def _query_powershell(class_name, namespace):
        executable = shutil.which("powershell.exe") or shutil.which("powershell")
        if not executable:
            return None
        command = (
            f"Get-CimInstance -Namespace '{namespace}' -ClassName '{class_name}' "
            "| Select-Object * | ConvertTo-Json -Depth 4 -Compress"
        )
        try:
            completed = subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                check=False,
            )
            if completed.returncode:
                logger.warning(
                    "CIM no pudo consultar %s (%s): %s",
                    class_name,
                    namespace,
                    completed.stderr.strip() or "código de salida no exitoso",
                )
                return []
            output = completed.stdout.strip()
            if not output:
                return []
            result = json.loads(output)
            return result if isinstance(result, list) else [result]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            logger.warning(
                "Falló la consulta CIM de %s (%s)", class_name, namespace,
                exc_info=True,
            )
            return []

    def cpu(self):
        processors = self._query("Win32_Processor")
        processor = processors[0] if processors else None
        try:
            frequency = psutil.cpu_freq()
        except (OSError, RuntimeError):
            logger.warning("No se pudo obtener la frecuencia de CPU", exc_info=True)
            frequency = None
        try:
            usage = psutil.cpu_percent(interval=0.2)
        except (OSError, RuntimeError):
            logger.warning("No se pudo obtener el uso de CPU", exc_info=True)
            usage = None

        architecture = platform.machine() or None
        architecture_codes = {0: "x86", 5: "ARM", 9: "x64", 12: "ARM64"}
        architecture = (
            architecture_codes.get(_integer(_value(processor, "Architecture")))
            or architecture
        )
        try:
            process_count = len(psutil.pids())
        except (OSError, RuntimeError):
            logger.warning("No se pudo obtener la cantidad de procesos", exc_info=True)
            process_count = None
        return {
            "model": _text(_value(processor, "Name")),
            "manufacturer": _text(_value(processor, "Manufacturer")),
            "name": _text(_value(processor, "Caption")),
            "architecture": architecture,
            "physical_cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "current_frequency_mhz": (
                round(frequency.current, 1) if frequency else None
            ),
            "max_frequency_mhz": (
                round(frequency.max, 1) if frequency and frequency.max else None
            ),
            "usage_percent": usage,
            "process_count": process_count,
            "temperature_c": self._cpu_temperature(),
            "socket": _text(_value(processor, "SocketDesignation")),
            "l2_cache_kb": _integer(_value(processor, "L2CacheSize")),
            "l3_cache_kb": _integer(_value(processor, "L3CacheSize")),
            "processor_id": _text(_value(processor, "ProcessorId")),
            "status": _text(_value(processor, "Status")),
        }

    @staticmethod
    def _cpu_temperature():
        if not hasattr(psutil, "sensors_temperatures"):
            logger.info("psutil no expone sensores de temperatura en esta plataforma")
            return None
        try:
            for sensor, readings in psutil.sensors_temperatures().items():
                for reading in readings:
                    label = f"{sensor} {reading.label or ''}".casefold()
                    if (
                        reading.current is not None
                        and any(token in label for token in ("cpu", "core", "package"))
                    ):
                        return reading.current
        except (OSError, RuntimeError):
            logger.warning(
                "El proveedor de temperatura de CPU no está disponible",
                exc_info=True,
            )
        return None

    def ram(self):
        memory = psutil.virtual_memory()
        modules = []
        for stick in self._query("Win32_PhysicalMemory"):
            memory_type = (
                _integer(_value(stick, "SMBIOSMemoryType"))
                or _integer(_value(stick, "MemoryType"))
            )
            modules.append(
                {
                    "capacity_bytes": _integer(_value(stick, "Capacity")),
                    "capacity_gb": _gb(_value(stick, "Capacity")),
                    "manufacturer": _text(_value(stick, "Manufacturer")),
                    "part_number": _text(_value(stick, "PartNumber")),
                    "serial_number": _text(_value(stick, "SerialNumber")),
                    "device_locator": _text(_value(stick, "DeviceLocator")),
                    "bank_label": _text(_value(stick, "BankLabel")),
                    "memory_type_code": memory_type,
                    "memory_type": RAM_TYPES.get(memory_type, "Otro" if memory_type else None),
                    "speed_mhz": _integer(_value(stick, "Speed")),
                    "configured_speed_mhz": _integer(
                        _value(stick, "ConfiguredClockSpeed")
                    ),
                }
            )

        arrays = self._query("Win32_PhysicalMemoryArray")
        array = arrays[0] if arrays else None
        maximum_kb = _integer(_value(array, "MaxCapacity"))
        maximum_bytes = maximum_kb * 1024 if maximum_kb and maximum_kb > 0 else None
        installed_slots = len(modules)
        slot_count = _integer(_value(array, "MemoryDevices"))
        maximum = {
            "capacity_gb": _gb(maximum_bytes),
            "source": "SMBIOS" if maximum_bytes else None,
            "confidence": "reported_by_smbios" if maximum_bytes else "unknown",
        }
        return {
            "installed_bytes": (
                sum(module["capacity_bytes"] or 0 for module in modules) or None
            ),
            "installed_gb": (
                _gb(sum(module["capacity_bytes"] or 0 for module in modules))
                if modules
                else None
            ),
            "total_bytes": memory.total,
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "available_bytes": memory.available,
            "available_gb": round(memory.available / (1024 ** 3), 2),
            "used_bytes": memory.used,
            "used_gb": round(memory.used / (1024 ** 3), 2),
            "usage_percent": memory.percent,
            "modules": modules,
            "module_count": len(modules),
            "slot_count": slot_count,
            "occupied_slots": installed_slots,
            "free_slots": (
                max(0, slot_count - installed_slots) if slot_count is not None else None
            ),
            "memory_type": self._common_value(modules, "memory_type"),
            "speed_mhz": self._common_value(modules, "speed_mhz"),
            "channel_configuration": None,
            "maximum_capacity": maximum,
            "maximum_capacity_extended_gb": _gb(_value(array, "MaxCapacityEx")),
        }

    @staticmethod
    def _common_value(records, key):
        values = {record.get(key) for record in records if record.get(key) is not None}
        return next(iter(values)) if len(values) == 1 else None

    def storage(self):
        physical = []
        physical_details = self._query(
            "MSFT_PhysicalDisk", namespace=r"root\Microsoft\Windows\Storage"
        )
        disk_records = self._query("Win32_DiskDrive")
        partition_to_disk = {}
        for association in self._query("Win32_DiskDriveToDiskPartition"):
            disk_index = self._disk_index(_value(association, "Antecedent"))
            partition = _value(association, "Dependent")
            partition_number = self._partition_number(partition)
            if disk_index is not None and partition_number is not None:
                partition_to_disk[f"{disk_index}:{partition_number}"] = disk_index
        volume_to_disk = {}
        for association in self._query("Win32_LogicalDiskToPartition"):
            partition = _value(association, "Antecedent")
            disk_index = self._disk_index(partition)
            partition_number = self._partition_number(partition)
            dependent = _text(_value(association, "Dependent")) or ""
            letter_match = re.search(r'DeviceID="([A-Z]:)"', dependent, re.IGNORECASE)
            if (
                disk_index is not None
                and partition_number is not None
                and letter_match
                and f"{disk_index}:{partition_number}" in partition_to_disk
            ):
                volume_to_disk[letter_match.group(1).upper()] = disk_index

        for disk in disk_records:
            model = _text(_value(disk, "Model"))
            pnp_id = _text(_value(disk, "PNPDeviceID"))
            interface = _text(_value(disk, "InterfaceType"))
            text = f"{model or ''} {pnp_id or ''} {interface or ''}".upper()
            media_type = _text(_value(disk, "MediaType"))
            serial = _text(_value(disk, "SerialNumber"))
            detail = next(
                (
                    item
                    for item in physical_details
                    if (
                        serial
                        and _text(_value(item, "SerialNumber"))
                        and serial.casefold()
                        == _text(_value(item, "SerialNumber")).casefold()
                    )
                    or (
                        model
                        and _text(_value(item, "FriendlyName"))
                        and model.casefold()
                        == _text(_value(item, "FriendlyName")).casefold()
                    )
                ),
                None,
            )
            bus_types = {11: "SATA", 17: "NVMe", 7: "USB"}
            detail_bus = bus_types.get(_integer(_value(detail, "BusType")))
            detail_media = _integer(_value(detail, "MediaType"))
            if "NVME" in text:
                drive_type, protocol = "SSD", "NVMe"
            elif "SATA" in text or detail_bus == "SATA":
                drive_type = (
                    "SSD" if "SSD" in text else "HDD" if "HARD DISK" in text else None
                )
                protocol = "SATA"
            elif "SSD" in text or "SOLID STATE" in (media_type or "").upper():
                drive_type, protocol = "SSD", interface
            elif "HARD DISK" in (media_type or "").upper():
                drive_type, protocol = "HDD", interface
            elif detail_media in (3, 4):
                drive_type = "HDD" if detail_media == 3 else "SSD"
                protocol = detail_bus or interface
            else:
                drive_type, protocol = None, interface
            health_codes = {0: "normal", 1: "warning", 2: "problem", 5: None}
            health = health_codes.get(_integer(_value(detail, "HealthStatus")))
            detail_health = _text(_value(detail, "HealthStatus"))
            if not health and detail_health:
                health = {
                    "healthy": "normal",
                    "warning": "warning",
                    "unhealthy": "problem",
                }.get(detail_health.casefold())
            physical.append(
                {
                    "model": model,
                    "manufacturer": _text(_value(disk, "Manufacturer")),
                    "serial_number": serial,
                    "device_id": _text(_value(disk, "DeviceID")),
                    "pnp_device_id": pnp_id,
                    "capacity_bytes": _integer(_value(disk, "Size")),
                    "capacity_gb": _gb(_value(disk, "Size")),
                    "interface": interface,
                    "protocol": protocol,
                    "drive_type": drive_type,
                    "media_type": media_type,
                    "partitions": _integer(_value(disk, "Partitions")),
                    "status": _text(_value(disk, "Status")),
                    "health": health or self._disk_health(pnp_id or _value(disk, "DeviceID")),
                    "temperature_c": _integer(_value(detail, "Temperature")),
                }
            )

        volumes = []
        physical_by_index = {}
        for index, disk in enumerate(physical):
            disk_number = self._disk_index(disk["device_id"])
            if disk_number is None:
                disk_number = index
            physical_by_index[disk_number] = disk
        seen = set()
        try:
            partitions = psutil.disk_partitions(all=False)
        except (OSError, RuntimeError):
            logger.warning("No se pudieron enumerar los volúmenes", exc_info=True)
            partitions = []
        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                key = (partition.device, partition.mountpoint)
                if key in seen:
                    continue
                seen.add(key)
                letter = (partition.device or "").rstrip("\\").upper()
                physical_index = volume_to_disk.get(letter)
                linked_disk = physical_by_index.get(physical_index)
                volumes.append(
                    {
                        "letter": partition.device,
                        "mountpoint": partition.mountpoint,
                        "physical_drive_index": physical_index,
                        "physical_drive_model": (
                            linked_disk["model"] if linked_disk else None
                        ),
                        "filesystem": partition.fstype or None,
                        "total_bytes": usage.total,
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_bytes": usage.used,
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "free_bytes": usage.free,
                        "free_gb": round(usage.free / (1024 ** 3), 2),
                        "usage_percent": usage.percent,
                        "health": None,
                    }
                )
            except (OSError, PermissionError):
                logger.warning(
                    "No se pudo leer el volumen %s", partition.mountpoint,
                    exc_info=True,
                )
        return {"physical_drives": physical, "volumes": volumes}

    @staticmethod
    def _disk_index(reference):
        text = _text(reference) or ""
        match = re.search(r"PHYSICALDRIVE(\d+)", text, re.IGNORECASE)
        if not match:
            match = re.search(r"Disk\s*#\s*(\d+)", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _partition_number(reference):
        match = re.search(
            r"Partition\s*#\s*(\d+)", _text(reference) or "", re.IGNORECASE
        )
        return int(match.group(1)) if match else None

    def _disk_health(self, device_id):
        statuses = self._query(
            "MSStorageDriver_FailurePredictStatus", namespace=r"root\wmi"
        )
        for status in statuses:
            instance = _text(_value(status, "InstanceName"))
            if device_id and instance and device_id.casefold() in instance.casefold():
                predicted = _value(status, "PredictFailure")
                return "problem" if predicted is True or str(predicted).lower() == "true" else "normal"
        return None

    def gpu(self):
        controllers = self._query("Win32_VideoController")
        try:
            import GPUtil

            metrics = {gpu.name.casefold(): gpu for gpu in GPUtil.getGPUs()}
        except Exception:
            metrics = {}
            logger.warning("Métricas GPUtil no disponibles", exc_info=True)

        cards = []
        for controller in controllers:
            name = _text(_value(controller, "Name"))
            metric = next(
                (value for key, value in metrics.items() if name and key in name.casefold()),
                None,
            )
            memory_bytes = _integer(_value(controller, "AdapterRAM"))
            if memory_bytes is not None and memory_bytes <= 0:
                memory_bytes = None
            cards.append(
                {
                    "name": name,
                    "manufacturer": _text(_value(controller, "AdapterCompatibility")),
                    "dedicated_memory_bytes": memory_bytes,
                    "dedicated_memory_mb": (
                        round(memory_bytes / (1024 ** 2), 1) if memory_bytes else None
                    ),
                    "shared_memory_bytes": None,
                    "usage_percent": round(metric.load * 100, 1) if metric else None,
                    "temperature_c": metric.temperature if metric else None,
                    "driver_version": _text(_value(controller, "DriverVersion")),
                    "driver_date": _text(_value(controller, "DriverDate")),
                    "status": _text(_value(controller, "Status")),
                    "resolution": self._resolution(controller),
                    "refresh_rate_hz": _integer(
                        _value(controller, "CurrentRefreshRate")
                    ),
                    "pnp_device_id": _text(_value(controller, "PNPDeviceID")),
                }
            )
        return {"cards": cards, "detected": bool(cards)}

    @staticmethod
    def _resolution(controller):
        width = _integer(_value(controller, "CurrentHorizontalResolution"))
        height = _integer(_value(controller, "CurrentVerticalResolution"))
        return f"{width}x{height}" if width and height else None

    def motherboard(self):
        boards = self._query("Win32_BaseBoard")
        board = boards[0] if boards else None
        arrays = self._query("Win32_PhysicalMemoryArray")
        slots = _integer(_value(arrays[0], "MemoryDevices")) if arrays else None
        chipset_devices = []
        for device in self._query("Win32_PnPEntity"):
            name = _text(_value(device, "Name"))
            if name and "chipset" in name.casefold():
                chipset_devices.append(name)
        return {
            "manufacturer": _text(_value(board, "Manufacturer")),
            "model": _text(_value(board, "Product")),
            "serial_number": _text(_value(board, "SerialNumber")),
            "version": _text(_value(board, "Version")),
            "chipset": chipset_devices or None,
            "memory_slots_reported": slots,
            "product": _text(_value(board, "Product")),
            "asset_tag": _text(_value(board, "Tag")),
        }

    def bios(self):
        bios_records = self._query("Win32_BIOS")
        bios = bios_records[0] if bios_records else None
        systems = self._query("Win32_ComputerSystem")
        system = systems[0] if systems else None
        firmware_type = _integer(_value(system, "FirmwareType"))
        firmware_modes = {1: "BIOS", 2: "UEFI"}
        smbios_major = _integer(_value(bios, "SMBIOSMajorVersion"))
        smbios_minor = _integer(_value(bios, "SMBIOSMinorVersion"))
        smbios_version = (
            f"{smbios_major}.{smbios_minor}"
            if smbios_major is not None and smbios_minor is not None
            else str(smbios_major) if smbios_major is not None else None
        )
        return {
            "manufacturer": _text(_value(bios, "Manufacturer")),
            "version": _text(_value(bios, "SMBIOSBIOSVersion"))
            or _text(_value(bios, "Version")),
            "release_date": _dmtf_date(_value(bios, "ReleaseDate")),
            "release_date_raw": _text(_value(bios, "ReleaseDate")),
            "mode": firmware_modes.get(firmware_type),
            "firmware_type_code": firmware_type,
            "serial_number": _text(_value(bios, "SerialNumber")),
            "smbios_version": smbios_version,
            "system_manufacturer": _text(_value(system, "Manufacturer")),
            "system_model": _text(_value(system, "Model")),
        }

    def battery(self):
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, OSError, RuntimeError):
            logger.warning("No se pudo consultar la batería con psutil", exc_info=True)
            battery = None
        if not battery:
            return {"detected": False}

        batteries = self._query("Win32_Battery")
        record = batteries[0] if batteries else None
        battery_static = self._query("BatteryStaticData", namespace=r"root\wmi")
        battery_charge = self._query(
            "BatteryFullChargedCapacity", namespace=r"root\wmi"
        )
        static_data = battery_static[0] if battery_static else None
        charge_data = battery_charge[0] if battery_charge else None
        design = (
            _integer(_value(record, "DesignCapacity"))
            or _integer(_value(static_data, "DesignedCapacity"))
        )
        full_charge = (
            _integer(_value(record, "FullChargeCapacity"))
            or _integer(_value(charge_data, "FullChargedCapacity"))
        )
        health = round(full_charge * 100 / design, 1) if design and full_charge else None
        seconds = battery.secsleft if battery.secsleft >= 0 else None
        cycles = next(
            (
                _integer(_value(item, "CycleCount"))
                for item in self._query("BatteryCycleCount", namespace=r"root\wmi")
                if _integer(_value(item, "CycleCount")) is not None
            ),
            None,
        )
        return {
            "detected": True,
            "percentage": battery.percent,
            "power_connected": battery.power_plugged,
            "time_remaining_seconds": seconds,
            "status": _text(_value(record, "Status")),
            "design_capacity_mwh": design,
            "full_charge_capacity_mwh": full_charge,
            "health_percent": health,
            "cycle_count": cycles,
            "chemistry": _text(_value(record, "Chemistry")),
            "device_name": _text(_value(record, "Name")),
        }

    def display(self):
        gpu_cards = self.gpu()["cards"]
        monitors = self._query("Win32_DesktopMonitor")
        monitor_ids = self._query("WmiMonitorID", namespace=r"root\wmi")
        display_params = self._query(
            "WmiMonitorBasicDisplayParams", namespace=r"root\wmi"
        )
        details = []
        monitor_count = max(len(monitors), len(monitor_ids))
        for index in range(monitor_count):
            monitor = monitors[index] if index < len(monitors) else None
            edid = monitor_ids[index] if index < len(monitor_ids) else None
            parameters = display_params[index] if index < len(display_params) else None
            details.append(
                {
                    "name": self._decode_edid(_value(edid, "UserFriendlyName"))
                    or _text(_value(monitor, "Name")),
                    "manufacturer": self._decode_edid(
                        _value(edid, "ManufacturerName")
                    )
                    or _text(_value(monitor, "MonitorManufacturer")),
                    "model": self._decode_edid(_value(edid, "ProductCodeID")),
                    "size_inches": self._monitor_size(parameters),
                    "screen_width": _integer(_value(monitor, "ScreenWidth")),
                    "screen_height": _integer(_value(monitor, "ScreenHeight")),
                    "status": _text(_value(monitor, "Status")),
                    "edid_available": edid is not None,
                }
            )
        return {
            "monitor_count": monitor_count or None,
            "monitors": details,
            "resolution": next(
                (card["resolution"] for card in gpu_cards if card["resolution"]), None
            ),
            "refresh_rate_hz": next(
                (card["refresh_rate_hz"] for card in gpu_cards if card["refresh_rate_hz"]),
                None,
            ),
            "gpu_names": [card["name"] for card in gpu_cards if card["name"]],
        }

    @staticmethod
    def _decode_edid(value):
        if not isinstance(value, (list, tuple)):
            return _text(value)
        characters = [chr(code) for code in value if _integer(code) not in (None, 0)]
        return "".join(characters).strip() or None

    @staticmethod
    def _monitor_size(parameters):
        width = _integer(_value(parameters, "MaxHorizontalImageSize"))
        height = _integer(_value(parameters, "MaxVerticalImageSize"))
        if not width or not height:
            return None
        return round(((width ** 2 + height ** 2) ** 0.5) / 2.54, 1)

    def audio(self):
        devices = []
        for device in self._query("Win32_SoundDevice"):
            devices.append(
                {
                    "name": _text(_value(device, "Name")),
                    "manufacturer": _text(_value(device, "Manufacturer")),
                    "status": _text(_value(device, "Status")),
                    "device_id": _text(_value(device, "DeviceID")),
                    "pnp_device_id": _text(_value(device, "PNPDeviceID")),
                    "driver_version": _text(_value(device, "DriverVersion")),
                }
            )
        for device in self._query("Win32_PnPEntity"):
            name = _text(_value(device, "Name"))
            category = _text(_value(device, "PNPClass"))
            if category and category.casefold() == "audio" and name:
                identifier = _text(_value(device, "DeviceID"))
                if not any(item["device_id"] == identifier for item in devices):
                    devices.append(
                        {
                            "name": name,
                            "manufacturer": _text(_value(device, "Manufacturer")),
                            "status": _text(_value(device, "Status")),
                            "device_id": identifier,
                            "pnp_device_id": _text(_value(device, "PNPDeviceID")),
                            "driver_version": None,
                        }
                    )
        return {
            "playback_devices": None,
            "recording_devices": None,
            "devices": devices,
        }

    def devices(self):
        categories = {
            "usb": [],
            "bluetooth": [],
            "cameras": [],
            "printers": [],
            "network_adapters": [],
            "audio": [],
            "other": [],
        }
        for device in self._query("Win32_PnPEntity"):
            name = _text(_value(device, "Name"))
            if not name:
                continue
            pnp_id = _text(_value(device, "PNPDeviceID"))
            device_class = _text(_value(device, "PNPClass"))
            haystack = f"{name} {pnp_id or ''} {device_class or ''}".casefold()
            if "usb" in haystack:
                category = "usb"
            elif "bluetooth" in haystack:
                category = "bluetooth"
            elif "camera" in haystack or "webcam" in haystack:
                category = "cameras"
            elif "printer" in haystack:
                category = "printers"
            elif device_class and device_class.casefold() == "net":
                category = "network_adapters"
            elif device_class and device_class.casefold() == "audio":
                category = "audio"
            else:
                category = "other"
            categories[category].append(
                {
                    "name": name,
                    "manufacturer": _text(_value(device, "Manufacturer")),
                    "status": _text(_value(device, "Status")),
                    "problem_code": _integer(_value(device, "ConfigManagerErrorCode")),
                    "problem": self._device_problem(
                        _integer(_value(device, "ConfigManagerErrorCode"))
                    ),
                    "type": device_class or category,
                    "device_id": _text(_value(device, "DeviceID")),
                    "pnp_device_id": pnp_id,
                }
            )
        for adapter in self._query("Win32_NetworkAdapter"):
            if _value(adapter, "PhysicalAdapter") is True:
                identifier = _text(_value(adapter, "PNPDeviceID"))
                if not any(
                    item["pnp_device_id"] == identifier
                    for item in categories["network_adapters"]
                ):
                    categories["network_adapters"].append(
                        {
                            "name": _text(_value(adapter, "Name")),
                            "manufacturer": _text(_value(adapter, "Manufacturer")),
                            "status": _text(_value(adapter, "NetConnectionStatus")),
                            "problem_code": _integer(
                                _value(adapter, "ConfigManagerErrorCode")
                            ),
                            "problem": self._device_problem(
                                _integer(_value(adapter, "ConfigManagerErrorCode"))
                            ),
                            "type": "Adaptador de red",
                            "device_id": _text(_value(adapter, "DeviceID")),
                            "pnp_device_id": identifier,
                        }
                    )
        return categories

    @staticmethod
    def _device_problem(code):
        if code is None:
            return None
        if code == 0:
            return "Sin problema reportado"
        return f"Windows reportó código de problema {code}"

    def network(self):
        adapters = []
        for adapter in self._query("Win32_NetworkAdapter"):
            if _value(adapter, "PhysicalAdapter") is False:
                continue
            adapters.append(
                {
                    "name": _text(_value(adapter, "Name")),
                    "manufacturer": _text(_value(adapter, "Manufacturer")),
                    "status": _text(_value(adapter, "NetConnectionStatus")),
                    "mac_address": _text(_value(adapter, "MACAddress")),
                    "speed_bps": _integer(_value(adapter, "Speed")),
                    "adapter_type": _text(_value(adapter, "AdapterType")),
                    "pnp_device_id": _text(_value(adapter, "PNPDeviceID")),
                }
            )
        return {"adapters": adapters}

    @staticmethod
    def system():
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = max(0, int(time.time() - boot_time))
        except (OSError, RuntimeError):
            logger.warning("No se pudo obtener el tiempo de actividad", exc_info=True)
            boot_time = None
            uptime_seconds = None
        return {
            "computer_name": platform.node() or None,
            "os": platform.platform() or None,
            "windows_version": platform.version() or None,
            "architecture": platform.machine() or None,
            "boot_time_epoch": boot_time,
            "uptime_seconds": uptime_seconds,
            "pending_updates": None,
            "pending_updates_source": None,
            "recent_system_errors": None,
        }

    def complete(self):
        data = {
            "system": self.system(),
            "cpu": self.cpu(),
            "ram": self.ram(),
            "storage": self.storage(),
            "gpu": self.gpu(),
            "motherboard": self.motherboard(),
            "bios": self.bios(),
            "battery": self.battery(),
            "network": self.network(),
        }
        data["overall_status"] = self._overall_status(data)
        return data

    @staticmethod
    def _overall_status(data):
        parts = {}
        cpu_usage = data["cpu"]["usage_percent"]
        parts["cpu"] = (
            "unknown" if cpu_usage is None
            else "alert" if cpu_usage >= 90
            else "normal"
        )

        ram_usage = data["ram"]["usage_percent"]
        parts["ram"] = "alert" if ram_usage >= 90 else "normal"

        volumes = data["storage"]["volumes"]
        disk_alert = any(
            volume["usage_percent"] >= 90
            or (volume["free_bytes"] is not None and volume["free_bytes"] < 2 * 1024 ** 3)
            for volume in volumes
        ) or any(
            drive["health"] in ("warning", "problem")
            or (drive["status"] or "").casefold() in ("pred fail", "error")
            for drive in data["storage"]["physical_drives"]
        )
        parts["storage"] = (
            "alert" if disk_alert
            else "normal" if volumes or data["storage"]["physical_drives"]
            else "unknown"
        )

        gpu_statuses = [card["status"] for card in data["gpu"]["cards"]]
        reported_gpu_statuses = [status for status in gpu_statuses if status]
        parts["gpu"] = (
            "unknown" if not reported_gpu_statuses
            else "alert"
            if any(status.casefold() != "ok" for status in reported_gpu_statuses)
            else "normal"
        )
        battery = data["battery"]
        if not battery.get("detected"):
            parts["battery"] = "unknown"
        elif battery.get("health_percent") is not None:
            parts["battery"] = (
                "alert" if battery["health_percent"] < 60 else "normal"
            )
        elif battery.get("status"):
            parts["battery"] = (
                "normal" if battery["status"].casefold() == "ok" else "alert"
            )
        else:
            parts["battery"] = "unknown"
        known_states = [state for state in parts.values() if state != "unknown"]
        state = (
            "alert" if "alert" in known_states
            else "normal" if known_states
            else "unknown"
        )
        return {"components": parts, "state": state}

    def expansion(self):
        memory = self.ram()
        disks = self.storage()
        record = None
        try:
            equipment = CatalogoAmpliacion.detectar_equipo()
        except Exception:
            logger.warning("No se pudo detectar el modelo para el catálogo", exc_info=True)
            equipment = None
        if equipment:
            try:
                record = CatalogoAmpliacion().buscar_equipo(
                    equipment["marca"], equipment["modelo"]
                )
            except (OSError, ValueError, sqlite3.Error):
                logger.warning("No se pudo consultar el catálogo de ampliación", exc_info=True)

        maximum = memory["maximum_capacity"]
        confidence = maximum["confidence"]
        source = maximum["source"]
        if (
            record
            and record.get("ram_max_gb") is not None
            and record.get("fuente")
            and record.get("verificado_el")
        ):
            maximum = {
                "capacity_gb": record["ram_max_gb"],
                "source": record.get("fuente"),
                "confidence": "confirmed",
                "verified_on": record.get("verificado_el"),
            }
            confidence = "confirmed"
            source = record.get("fuente")

        nvme_count = sum(
            1 for drive in disks["physical_drives"] if drive["protocol"] == "NVMe"
        )
        sata_count = sum(
            1
            for drive in disks["physical_drives"]
            if drive["protocol"] == "SATA"
        )
        storage_interfaces = record.get("interfaces_almacenamiento") if record else None
        return {
            "ram": {
                "installed_gb": memory["installed_gb"],
                "slot_count": memory["slot_count"],
                "occupied_slots": memory["occupied_slots"],
                "free_slots": memory["free_slots"],
                "memory_type": memory["memory_type"],
                "speed_mhz": memory["speed_mhz"],
                "module_capacities_gb": [
                    module["capacity_gb"] for module in memory["modules"]
                ],
                "maximum_capacity": maximum,
                "maximum_source": source,
                "confidence": confidence,
                "expansion_possible": (
                    memory["free_slots"] > 0
                    if memory["free_slots"] is not None
                    else None
                ),
            },
            "storage": {
                "physical_drives": disks["physical_drives"],
                "current_capacity_gb": sum(
                    drive["capacity_gb"] or 0 for drive in disks["physical_drives"]
                )
                or None,
                "nvme_devices_detected": nvme_count,
                "sata_devices_detected": sata_count,
                "m2_slots_detected": None,
                "interfaces_reported_by_catalog": storage_interfaces,
                "free_slots": None,
                "expansion_possible": (
                    "possible_by_catalog" if storage_interfaces else "unknown"
                ),
                "confidence": "reported_by_catalog" if storage_interfaces else "unknown",
            },
        }
