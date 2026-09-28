"""CMD presentation for the structured hardware inventory."""

from modules.hardware import HardwareInfo
from ui.components import pausar


SEPARATOR = "─" * 44


class HardwareMenu:
    OPTIONS = {
        "1": ("PROCESADOR", "cpu"),
        "2": ("MEMORIA RAM", "ram"),
        "3": ("ALMACENAMIENTO", "storage"),
        "4": ("TARJETA GRÁFICA", "gpu"),
        "5": ("PLACA BASE", "motherboard"),
        "6": ("BIOS / UEFI", "bios"),
        "7": ("BATERÍA", "battery"),
        "8": ("PANTALLA", "display"),
        "9": ("AUDIO", "audio"),
        "10": ("DISPOSITIVOS CONECTADOS", "devices"),
        "11": ("INFORMACIÓN COMPLETA", "complete"),
        "12": ("CAPACIDAD DE EXPANSIÓN", "expansion"),
    }

    LABELS = {
        "model": "Modelo",
        "name": "Nombre completo",
        "manufacturer": "Fabricante",
        "architecture": "Arquitectura",
        "physical_cores": "Núcleos físicos",
        "threads": "Hilos",
        "current_frequency_mhz": "Frecuencia actual",
        "max_frequency_mhz": "Frecuencia máxima",
        "usage_percent": "Uso actual",
        "process_count": "Procesos",
        "temperature_c": "Temperatura",
        "dedicated_memory_mb": "Memoria dedicada (MB)",
        "shared_memory_bytes": "Memoria compartida (bytes)",
        "mac_address": "Dirección MAC",
        "speed_bps": "Velocidad (bps)",
        "total_gb": "RAM total visible a Windows",
        "installed_gb": "Total instalada",
        "physical_drive_model": "Disco físico",
        "physical_drive_index": "Índice del disco físico",
        "used_gb": "En uso",
        "available_gb": "Disponible",
        "usage_percent": "Uso",
        "memory_type": "Tipo de memoria",
        "speed_mhz": "Velocidad",
        "module_count": "Módulos instalados",
        "slot_count": "Slots reportados",
        "free_slots": "Slots disponibles reportados",
        "capacity_gb": "Capacidad",
        "part_number": "Número de parte",
        "device_locator": "Slot",
        "current_frequency_mhz": "Frecuencia actual",
        "serial_number": "Número de serie",
        "capacity_bytes": "Capacidad en bytes",
        "capacity_gb": "Capacidad",
        "interface": "Interfaz",
        "protocol": "Protocolo",
        "drive_type": "Tipo",
        "health": "Salud",
        "free_gb": "Libre",
        "used_gb": "Usado",
        "refresh_rate_hz": "Frecuencia de actualización",
        "resolution": "Resolución",
        "driver_version": "Versión del controlador",
        "driver_date": "Fecha del controlador",
        "status": "Estado del dispositivo",
        "mode": "Modo",
        "release_date": "Fecha",
        "manufacturer": "Fabricante",
        "percentage": "Porcentaje",
        "power_connected": "Conectada a corriente",
        "time_remaining_seconds": "Tiempo restante (segundos)",
        "design_capacity_mwh": "Capacidad de diseño (mWh)",
        "full_charge_capacity_mwh": "Capacidad máxima actual (mWh)",
        "health_percent": "Salud",
        "cycle_count": "Ciclos",
        "computer_name": "Nombre del equipo",
        "os": "Sistema operativo",
        "state": "Estado general",
    }

    def __init__(self, screens, catalog_callback=None):
        self.screens = screens
        self.catalog_callback = catalog_callback
        self.last_data = None

    def mostrar(self, profesional=False):
        while True:
            self.screens.mostrar_encabezado()
            print("╔════════════════════════════════════════════╗")
            print("║                 HARDWARE                   ║")
            print("║          Información del equipo            ║")
            print("╚════════════════════════════════════════════╝")
            for key, (title, _method) in self.OPTIONS.items():
                print(f"[{key}] {title.title()}")
            print("[T] Temperatura")
            if profesional and self.catalog_callback:
                print("[C] Catálogo de ampliación por modelo")
            print("[0] Volver")

            option = input("\nSelecciona un componente: ").strip().lower()
            if option == "0":
                return
            if option == "t":
                from modules.temperatura import TemperaturaInfo

                self.screens.mostrar_encabezado()
                temperature = TemperaturaInfo()
                temperature.mostrar(temperature.obtener(), profesional=profesional)
                pausar()
                continue
            if option == "c" and profesional and self.catalog_callback:
                self.catalog_callback()
                continue
            selected = self.OPTIONS.get(option)
            if not selected:
                print("Opción inválida.")
                pausar()
                continue

            title, method_name = selected
            collector = HardwareInfo()
            try:
                data = getattr(collector, method_name)()
            except Exception:
                import logging

                logging.getLogger("hardware_diagnostico").exception(
                    "Error recopilando el módulo hardware %s", method_name
                )
                data = {"error": "No fue posible completar la consulta."}
            self.last_data = {method_name: data}
            self.screens.mostrar_encabezado()
            print(title)
            print(SEPARATOR)
            if method_name == "complete":
                self._show_complete(data, profesional)
            elif method_name == "expansion":
                self._show_expansion(data, profesional)
            else:
                self._show_section(method_name, data, profesional)
            pausar()

    def _show_section(self, section, data, professional):
        if section == "cpu":
            keys = (
                "model", "manufacturer", "name", "architecture", "physical_cores",
                "threads", "current_frequency_mhz", "max_frequency_mhz",
                "usage_percent", "process_count", "temperature_c", "status",
            )
            self._show_fields(data, keys, professional)
            self._show_status(data.get("usage_percent"), 90, "uso del procesador")
        elif section == "ram":
            keys = (
                "installed_gb", "used_gb", "available_gb", "usage_percent",
                "memory_type", "speed_mhz", "module_count",
            )
            if professional:
                keys += ("total_gb", "slot_count", "free_slots", "channel_configuration")
            self._show_fields(data, keys, professional)
            print("\nMódulos:")
            if data.get("modules"):
                for index, module in enumerate(data["modules"], 1):
                    print(f"  [{index}]")
                    self._show_fields(
                        module,
                        ("capacity_gb", "memory_type", "speed_mhz", "manufacturer"),
                        professional,
                        indent="    ",
                    )
                    if professional:
                        self._show_fields(
                            module,
                            ("part_number", "serial_number", "device_locator", "bank_label"),
                            True,
                            indent="    ",
                        )
            else:
                print("  No disponible")
            maximum = data.get("maximum_capacity", {})
            if professional:
                self._show_fields(
                    maximum, ("capacity_gb", "source", "confidence"), professional
                )
        elif section == "storage":
            drives = data.get("physical_drives") or []
            volumes = data.get("volumes") or []
            print("Unidades físicas:")
            if drives:
                for index, drive in enumerate(drives, 1):
                    print(f"  Unidad física {index}")
                    keys = (
                        "model", "manufacturer", "drive_type", "protocol", "interface",
                        "capacity_gb", "status", "health", "temperature_c",
                    )
                    self._show_fields(drive, keys, professional, indent="    ")
                    if professional:
                        self._show_fields(
                            drive, ("serial_number", "device_id", "pnp_device_id"), True,
                            indent="    ",
                        )
            else:
                print("  No disponible")
            print("\nVolúmenes:")
            for volume in volumes:
                print(f"  {volume.get('letter') or volume.get('mountpoint') or 'Unidad'}")
                self._show_fields(
                    volume,
                    (
                        "physical_drive_model", "filesystem", "total_gb", "used_gb",
                        "free_gb", "usage_percent",
                    ),
                    professional,
                    indent="    ",
                )
                if professional:
                    self._show_fields(
                        volume, ("physical_drive_index",), True, indent="    "
                    )
            if not volumes:
                print("  No disponible")
        elif section == "gpu":
            cards = data.get("cards") or []
            if not cards:
                print("No disponible")
            for index, card in enumerate(cards, 1):
                print(f"GPU {index}: {card.get('name') or 'No disponible'}")
                keys = (
                    "manufacturer", "dedicated_memory_mb", "shared_memory_bytes",
                    "usage_percent", "temperature_c", "driver_version", "driver_date",
                    "resolution", "refresh_rate_hz", "status",
                )
                self._show_fields(card, keys, professional)
                if professional:
                    self._show_fields(card, ("pnp_device_id",), True)
        elif section == "motherboard":
            keys = ("manufacturer", "model", "serial_number", "version", "chipset", "memory_slots_reported")
            self._show_fields(data, keys, professional)
        elif section == "bios":
            keys = ("manufacturer", "version", "release_date", "mode", "system_manufacturer", "system_model")
            self._show_fields(data, keys, professional)
            if professional:
                self._show_fields(data, ("serial_number", "smbios_version", "firmware_type_code"), True)
        elif section == "battery":
            if not data.get("detected"):
                print("No se detectó batería.")
            else:
                keys = (
                    "percentage", "power_connected", "time_remaining_seconds", "status",
                    "health_percent",
                )
                self._show_fields(data, keys, professional)
                if professional:
                    self._show_fields(
                        data,
                        ("design_capacity_mwh", "full_charge_capacity_mwh", "cycle_count", "chemistry", "device_name"),
                        True,
                    )
        elif section == "display":
            keys = ("monitor_count", "resolution", "refresh_rate_hz", "gpu_names")
            self._show_fields(data, keys, professional)
            for index, monitor in enumerate(data.get("monitors") or [], 1):
                print(f"\nMonitor {index}")
                self._show_fields(
                    monitor,
                    ("name", "manufacturer", "screen_width", "screen_height", "status"),
                    professional,
                )
                if professional:
                    self._show_fields(monitor, ("model", "size_inches", "edid_available"), True)
        elif section == "audio":
            devices = data.get("devices") or []
            if not devices:
                print("No disponible")
            for index, device in enumerate(devices, 1):
                print(f"Dispositivo {index}")
                self._show_fields(
                    device,
                    ("name", "manufacturer", "direction", "status", "driver_version"),
                    professional,
                )
                if professional:
                    self._show_fields(device, ("device_id", "pnp_device_id"), True)
            print("\nWMI no distingue de forma fiable reproducción de grabación.")
        elif section == "devices":
            remaining = 40
            for category, devices in data.items():
                print(f"\n{category.replace('_', ' ').title()}:")
                if not devices:
                    print("  No disponible")
                    continue
                visible = devices if professional else devices[:remaining]
                for device in visible:
                    print(f"  • {device.get('name') or 'No disponible'}")
                    self._show_fields(
                        device, ("manufacturer", "status", "problem", "type"), professional,
                        indent="    ",
                    )
                    if professional:
                        self._show_fields(
                            device, ("problem_code", "device_id", "pnp_device_id"), True,
                            indent="    ",
                        )
                if not professional:
                    remaining -= len(visible)
                    if len(visible) < len(devices):
                        print(
                            f"  ... y {len(devices) - len(visible)} dispositivos más"
                        )
        elif "error" in data:
            print(data["error"])

    def _show_complete(self, data, professional):
        labels = (
            ("system", "SISTEMA"),
            ("cpu", "CPU"),
            ("ram", "RAM"),
            ("storage", "ALMACENAMIENTO"),
            ("gpu", "GPU"),
            ("motherboard", "PLACA BASE"),
            ("bios", "BIOS"),
            ("battery", "BATERÍA"),
            ("network", "RED"),
        )
        simple_keys = {
            "system": ("computer_name", "os", "architecture"),
            "cpu": ("model", "physical_cores", "threads", "usage_percent"),
            "ram": ("installed_gb", "used_gb", "available_gb", "usage_percent", "memory_type"),
            "motherboard": ("manufacturer", "model"),
            "bios": ("manufacturer", "version", "mode"),
            "battery": ("percentage", "power_connected", "health_percent"),
            "network": (),
        }
        for section, title in labels:
            print(f"\n{title}")
            value = data.get(section) or {}
            if section == "storage":
                drives = value.get("physical_drives") or []
                volumes = value.get("volumes") or []
                self._line("Unidades físicas", len(drives) if drives else None)
                for volume in volumes:
                    self._line(
                        f"{volume.get('letter') or 'Volumen'}: libre / total",
                        (
                            f"{volume['free_gb']} / {volume['total_gb']} GB"
                            if volume.get("free_gb") is not None
                            else None
                        ),
                    )
            elif section == "gpu":
                cards = value.get("cards") or []
                self._line(
                    "Modelos",
                    ", ".join(card["name"] for card in cards if card.get("name"))
                    if cards else None,
                )
                if professional:
                    for index, card in enumerate(cards, 1):
                        print(f"  GPU {index}")
                        self._show_fields(
                            card,
                            (
                                "manufacturer", "dedicated_memory_mb",
                                "shared_memory_bytes", "usage_percent",
                                "temperature_c", "driver_version", "driver_date",
                                "resolution", "refresh_rate_hz", "status",
                                "pnp_device_id",
                            ),
                            True,
                            indent="    ",
                        )
            elif section == "network":
                adapters = value.get("adapters") or []
                self._line("Adaptadores detectados", len(adapters) if adapters else None)
                if professional:
                    for index, adapter in enumerate(adapters, 1):
                        print(f"  Adaptador {index}")
                        self._show_fields(
                            adapter,
                            (
                                "name", "manufacturer", "status", "mac_address",
                                "speed_bps", "adapter_type", "pnp_device_id",
                            ),
                            True,
                            indent="    ",
                        )
            else:
                self._show_fields(value, simple_keys[section], professional)
            if professional and section == "storage":
                for index, drive in enumerate(value.get("physical_drives") or [], 1):
                    print(f"  Unidad física {index}")
                    self._show_fields(
                        drive,
                        (
                            "model", "manufacturer", "serial_number", "interface",
                            "protocol", "drive_type", "capacity_gb", "health",
                            "temperature_c",
                        ),
                        True,
                        indent="    ",
                    )
                self._show_fields(
                    value,
                    tuple(
                        key for key in value
                        if key not in ("physical_drives", "volumes")
                    ),
                    True,
                )
            if professional and section == "battery":
                self._show_fields(
                    value,
                    (
                        "status", "time_remaining_seconds", "design_capacity_mwh",
                        "full_charge_capacity_mwh", "health_percent", "cycle_count",
                        "chemistry", "device_name",
                    ),
                    True,
                )
            if professional and section in ("cpu", "ram", "motherboard", "bios"):
                self._show_fields(value, tuple(key for key in value if key not in simple_keys[section]), True)

        print("\nESTADO GENERAL")
        states = (data.get("overall_status") or {}).get("components", {})
        for key, label in (
            ("cpu", "CPU"), ("ram", "RAM"), ("storage", "DISCO"),
            ("gpu", "GPU"), ("battery", "BATERÍA"),
        ):
            state = states.get(key)
            icon = "⚠" if state == "alert" else "✓" if state == "normal" else "?"
            print(f"  {label:<10} {icon}")
        overall = (data.get("overall_status") or {}).get("state")
        self._line(
            "Estado general",
            {"normal": "✓ NORMAL", "alert": "⚠ ALERTA"}.get(
                overall, "? SIN DATOS SUFICIENTES"
            ),
        )

    def _show_expansion(self, data, professional):
        ram = data.get("ram") or {}
        storage = data.get("storage") or {}
        print("RAM")
        self._show_fields(
            ram,
            ("installed_gb", "slot_count", "occupied_slots", "free_slots", "memory_type", "speed_mhz"),
            professional,
        )
        print("\nMódulos:")
        capacities = ram.get("module_capacities_gb") or []
        if capacities:
            for index, capacity in enumerate(capacities, 1):
                print(f"  [{index}] {capacity:g} GB")
        else:
            print("  No disponible")
        maximum = ram.get("maximum_capacity") or {}
        self._line("Máximo", maximum.get("capacity_gb"), "GB")
        self._line("Fuente", maximum.get("source"))
        self._line(
            "Confianza",
            self._confidence(ram.get("confidence")),
        )
        expansion = ram.get("expansion_possible")
        self._line(
            "Posible expansión",
            "Sí, hay slots reportados" if expansion is True
            else "No se reportan slots libres" if expansion is False
            else "Desconocido",
        )
        print("\nALMACENAMIENTO")
        self._line("Capacidad actual", storage.get("current_capacity_gb"), "GB")
        self._line("Unidades NVMe detectadas", storage.get("nvme_devices_detected"))
        self._line("Unidades SATA detectadas", storage.get("sata_devices_detected"))
        self._line("Ranuras M.2 detectadas", storage.get("m2_slots_detected"))
        self._line("Ranuras libres", storage.get("free_slots"))
        self._line("Interfaces según catálogo", storage.get("interfaces_reported_by_catalog"))
        self._line(
            "Expansión",
            "ℹ POSIBLE (catálogo; no confirma ranura libre)"
            if storage.get("expansion_possible") == "possible_by_catalog"
            else "? DESCONOCIDO",
        )
        if professional:
            self._show_fields(storage, ("confidence",), True)

    def _show_fields(self, data, keys, professional, indent="  "):
        if not isinstance(data, dict):
            return
        technical_fields = {
            "serial_number", "device_id", "pnp_device_id", "processor_id",
            "part_number", "bank_label", "asset_tag", "driver_version",
            "driver_date", "smbios_version", "firmware_type_code",
            "memory_type_code", "capacity_bytes",
        }
        for key in keys:
            if key not in data:
                continue
            if not professional and key in technical_fields:
                continue
            value = data[key]
            if value is None or value == "":
                value = "No disponible"
            elif key in ("current_frequency_mhz", "max_frequency_mhz"):
                value = f"{value / 1000:.2f} GHz"
            elif key.endswith("_mhz"):
                value = f"{value} MHz"
            elif key in ("usage_percent", "health_percent", "percentage"):
                value = f"{value} %"
            elif key == "time_remaining_seconds":
                value = f"{int(value // 3600)} h {int((value % 3600) // 60)} min"
            elif key == "temperature_c":
                value = f"{value} °C"
            elif key in (
                "total_gb", "installed_gb", "used_gb", "available_gb",
                "free_gb", "capacity_gb",
            ):
                value = f"{value} GB"
            elif key == "power_connected":
                value = "Sí" if value else "No"
            elif key == "health":
                value = {
                    "normal": "✓ NORMAL",
                    "warning": "⚠ ALERTA",
                    "problem": "✖ PROBLEMA",
                }.get(value, value)
            elif isinstance(value, (dict, list)):
                value = self._format_nested(value)
            label = self.LABELS.get(key, key.replace("_", " ").title())
            self._line(label, value, indent=indent)

    @staticmethod
    def _format_nested(value):
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "No disponible"
        return ", ".join(f"{key}: {item}" for key, item in value.items() if item is not None) or "No disponible"

    @staticmethod
    def _line(label, value, unit="", indent="  "):
        if value is None or value == "":
            value = "No disponible"
        elif unit:
            value = f"{value} {unit}"
        print(f"{indent}{label:<29} {value}")

    @staticmethod
    def _show_status(value, threshold, label):
        if value is None:
            print("\nEstado: ? No disponible")
        elif value >= threshold:
            print(f"\nEstado: ⚠ ALERTA ({label} elevado)")
        else:
            print("\nEstado: ✓ NORMAL")

    @staticmethod
    def _confidence(value):
        return {
            "confirmed": "✓ CONFIRMADO",
            "reported_by_smbios": "ℹ REPORTADO POR SMBIOS",
            "reported_by_catalog": "ℹ REPORTADO POR CATÁLOGO",
            "estimated": "⚠ ESTIMADO",
            "unknown": "? DESCONOCIDO",
        }.get(value, "? DESCONOCIDO")
