"""CMD menu for Windows maintenance and confirmed actions."""

import logging

from core.actions import ActionRisk
from core.permissions import solicitar_autorizacion
from core.severity import Severity
from modules.mantenimiento import (
    CONFIRMATION_TOKEN,
    MaintenanceDiagnostics,
)
from ui.components import pausar


logger = logging.getLogger("hardware_diagnostico")


class MaintenanceMenu:
    def __init__(self, screens, history_logger=None):
        self.screens = screens
        self.history_logger = history_logger
        self.diagnostics = MaintenanceDiagnostics()
        self.last_result = None

    def mostrar(self, professional=False):
        while True:
            self.screens.mostrar_encabezado()
            self._menu(professional)
            option = input("\nSelecciona una opción: ").strip()
            if option == "0":
                return
            handlers = {
                "1": self._show_processes,
                "2": self._show_memory,
                "3": self._show_temporaries,
                "4": self._show_recycle_bin,
                "5": self._show_startup,
                "6": self._show_services,
                "7": self._show_storage,
                "8": self._show_recommended,
            }
            handler = handlers.get(option)
            if handler:
                handler(professional)
            else:
                print("Opción inválida.")
                pausar()

    @staticmethod
    def _menu(professional=False):
        print("╔════════════════════════════════════╗")
        print("║          MANTENIMIENTO             ║")
        print("╚════════════════════════════════════╝")
        options = (
            ("1", "Procesos"),
            ("2", "Liberar memoria"),
            ("3", "Archivos temporales"),
            ("4", "Papelera de reciclaje"),
            ("5", "Programas de inicio"),
            ("6", "Servicios"),
            ("7", "Almacenamiento"),
            ("8", "Mantenimiento recomendado"),
        )
        for number, title in options:
            if number == "6" and not professional:
                title = "Servicios (solo lectura)"
            elif number == "6":
                title = "Servicios y acciones profesionales"
            print(f"[{number}] {title}")
        print("[0] Volver")

    def _collect(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception:
            logger.exception("Falló una comprobación de mantenimiento")
            print("No fue posible obtener esta información.")
            return None

    def _show_processes(self, professional):
        self.screens.mostrar_encabezado()
        processes = self._collect(self.diagnostics.list_processes)
        print("PROCESOS")
        print("─" * 76)
        if processes is None:
            self._pause()
            return
        self._render_processes(processes, professional)
        self._persist(
            "Procesos",
            [
                {
                    key: value for key, value in process.items()
                    if key not in ("user",)
                }
                for process in processes
            ],
        )
        self._maybe_terminate(processes)
        self._pause()

    def _render_processes(self, processes, professional):
        if not processes:
            print("No hay procesos disponibles.")
            return
        print(
            f"{'#':>3} {'PID':>8} {'CPU %':>7} {'RAM MB':>10} "
            f"{'Estado':<14} {'Nombre'}"
        )
        for index, process in enumerate(processes, 1):
            cpu = _format(process.get("cpu_percent"))
            memory = _format(process.get("memory_mb"))
            print(
                f"{index:>3} {process['pid']:>8} {cpu:>7} {memory:>10} "
                f"{process['status']:<14} {process['name']}"
            )
            if professional:
                print(f"      Usuario: {process.get('user') or 'No disponible'}")

    def _show_memory(self, professional):
        self.screens.mostrar_encabezado()
        memory = self._collect(self.diagnostics.memory_info)
        print("MEMORIA")
        print("─" * 40)
        if memory is None:
            self._pause()
            return
        print(f"Total: {memory['total_gb']:.2f} GB")
        print(f"En uso: {memory['used_gb']:.2f} GB ({memory['usage_percent']:.1f}%)")
        print(f"Disponible: {memory['available_gb']:.2f} GB")
        print("\nProcesos con mayor consumo:")
        self._render_processes(memory["top_processes"], professional)
        print("\nNo se puede aumentar la RAM mediante liberación de memoria.")
        print("Elige procesos que reconozcas para cerrarlos.")
        self._maybe_terminate(memory["top_processes"])
        self._persist("Memoria", memory)
        self._pause()

    def _maybe_terminate(self, processes):
        if not processes:
            return
        choice = input(
            "\nNúmero de proceso para finalizar (0 = volver): "
        ).strip()
        if not choice.isdigit() or int(choice) == 0:
            return
        process = _selected(processes, choice)
        if process is None:
            print("Selección fuera de rango.")
            return
        print(
            f"Advertencia: se cerrará {process['name']} "
            f"(PID {process['pid']})."
        )
        token = self._confirm(
            "Escribe CONFIRMAR para finalizar el proceso: "
        )
        action = self._collect(
            self.diagnostics.terminate_process,
            process["pid"],
            token,
        )
        self._present_action(action)

    def _show_temporaries(self, professional):
        self.screens.mostrar_encabezado()
        inventory = self._collect(self.diagnostics.temporary_inventory)
        print("ARCHIVOS TEMPORALES")
        print("─" * 40)
        if inventory is None:
            self._pause()
            return
        self._line("Ubicaciones", "\n  ".join(inventory["locations"]) or None)
        self._line("Archivos aproximados", inventory["file_count"])
        self._line("Espacio ocupado", inventory["size_mb"], "MB")
        self._line(
            "Antiguos de 24 h eliminables",
            inventory["eligible_file_count"],
        )
        if inventory["truncated"]:
            print("  Conteo limitado para evitar bloquear el diagnóstico.")
        if professional:
            self._line("Errores de lectura", len(inventory["errors"]))
            for entry in inventory["files"][:20]:
                print(f"  {entry['size_bytes']:>12} bytes  {entry['path']}")
        self._persist("Inventario de temporales", _without_files(inventory))
        if inventory["eligible_file_count"]:
            print(
                f"\nSe eliminarán aproximadamente {inventory['eligible_size_mb']:.2f} MB "
                "de las ubicaciones temporales revisadas."
            )
            token = self._confirm(
                "Escriba CONFIRMAR para continuar: "
            )
            action = self._collect(
                self.diagnostics.delete_temporary_files,
                token,
            )
            self._present_action(action)
        elif inventory["file_count"]:
            print("No hay archivos con antigüedad superior a 24 horas para eliminar.")
        self._pause()

    def _show_recycle_bin(self, professional):
        self.screens.mostrar_encabezado()
        inventory = self._collect(self.diagnostics.recycle_bin_inventory)
        print("PAPELERA DE RECICLAJE")
        print("─" * 40)
        if inventory is None:
            self._pause()
            return
        self._line("Elementos", inventory["count"])
        self._line("Espacio aproximado", inventory["size_mb"], "MB")
        if not inventory["available"]:
            self._line("Estado", inventory.get("error"))
        elif inventory["count"]:
            token = self._confirm(
                "\nEscriba CONFIRMAR para vaciar la papelera: "
            )
            action = self._collect(
                self.diagnostics.empty_recycle_bin,
                token,
            )
            self._present_action(action)
        else:
            print("La papelera está vacía.")
        self._persist("Papelera", inventory)
        self._pause()

    def _show_startup(self, professional):
        self.screens.mostrar_encabezado()
        items = self._collect(
            self.diagnostics.startup_items,
            include_disabled=True,
        )
        print("PROGRAMAS DE INICIO")
        print("─" * 64)
        if items is None:
            self._pause()
            return
        if not items:
            print("No se detectaron entradas de inicio.")
            self._pause()
            return
        for index, item in enumerate(items, 1):
            state = "Habilitado" if item["enabled"] else "Deshabilitado"
            scope_note = (
                " — solo Modo Profesional para modificar"
                if item["scope"] == "machine" and not professional
                else ""
            )
            print(
                f"[{index}] {item['name']} — {state} ({item['scope']})"
                f"{scope_note}"
            )
            if professional:
                self._line("Origen", item["origin"], indent="    ")
                self._line("Comando", item["command"], indent="    ")
                self._line("ID", item["id"], indent="    ")
        choice = input(
            "\nNúmero para modificar; prefijo R para restaurar; "
            "0 = volver: "
        ).strip()
        if choice[:1].casefold() == "r" and choice[1:].isdigit():
            item = _selected(items, choice[1:])
            if item and not item["enabled"]:
                if item["scope"] == "machine" and not professional:
                    print("Esta entrada de equipo solo se puede modificar en Modo Profesional.")
                else:
                    token = self._confirm(
                        "Escriba CONFIRMAR para restaurar el inicio: "
                    )
                    action = self._collect(
                        self.diagnostics.restore_startup_item,
                        item["id"],
                        token,
                        professional=professional,
                    )
                    self._present_action(action)
        elif choice.isdigit() and int(choice) > 0:
            item = _selected(items, choice)
            if item and item["enabled"]:
                if item["scope"] == "machine" and not professional:
                    print("Esta entrada de equipo solo se puede modificar en Modo Profesional.")
                else:
                    token = self._confirm(
                        f"Se deshabilitará {item['name']} sin eliminarlo permanentemente. "
                        "Escriba CONFIRMAR: "
                    )
                    action = self._collect(
                        self.diagnostics.disable_startup_item,
                        item["id"],
                        token,
                        professional=professional,
                    )
                    self._present_action(action)
            elif item:
                print("Esta entrada ya está deshabilitada; use R para restaurarla.")
        self._persist(
            "Programas de inicio",
            [{"name": item["name"], "enabled": item["enabled"],
              "origin": item["origin"], "scope": item["scope"]}
             for item in items],
        )
        self._pause()

    def _show_services(self, professional):
        self.screens.mostrar_encabezado()
        services = self._collect(self.diagnostics.services_info)
        print("SERVICIOS")
        print("─" * 76)
        if services is None:
            self._pause()
            return
        if not services:
            print("Servicios relevantes no disponibles.")
            self._pause()
            return
        for index, service in enumerate(services, 1):
            print(
                f"[{index}] {service.get('DisplayName') or service.get('Name')} "
                f"— {service.get('State') or 'No disponible'}"
            )
            print(
                f"    Inicio: {service.get('StartMode') or 'No disponible'}"
            )
            if professional:
                self._line("Nombre", service.get("Name"), indent="    ")
                self._line("Descripción", service.get("Description"), indent="    ")
                self._line("Ruta", service.get("PathName"), indent="    ")
        self._persist("Servicios", services)
        if professional:
            choice = input(
                "\nNúmero de servicio a modificar (0 = volver): "
            ).strip()
            if choice.isdigit() and int(choice) > 0:
                service = _selected(services, choice)
                if service:
                    self._change_service(service)
        self._pause()

    def _change_service(self, service):
        name = service.get("Name")
        print("Acciones: [1] Iniciar  [2] Detener  [3] Reiniciar")
        choice = input("Operación: ").strip()
        operation = {"1": "start", "2": "stop", "3": "restart"}.get(choice)
        if not operation:
            print("Operación cancelada.")
            return
        risk = (
            ActionRisk.CONFIRMATION
            if operation == "restart" else ActionRisk.PROFESSIONAL
        )
        if operation == "restart":
            token = self._confirm(
                f"{ActionRisk.CONFIRMATION.display} Esta acción modificará "
                f"el estado de {name}. Escriba CONFIRMAR: "
            )
            if not token:
                print("Operación cancelada.")
                return
        else:
            approved = solicitar_autorizacion(
                risk,
                f"{operation.capitalize()} el servicio {name}.",
                modo_profesional=True,
                input_func=input,
            )
            if not approved:
                return
            token = CONFIRMATION_TOKEN
        action = self._collect(
            self.diagnostics.change_service,
            name,
            operation,
            token,
            professional=True,
        )
        self._present_action(action)

    def _show_storage(self, professional):
        self.screens.mostrar_encabezado()
        volumes = self._collect(
            self.diagnostics.storage_info,
            scan_directories=professional,
        )
        print("ALMACENAMIENTO")
        print("─" * 64)
        if volumes is None:
            self._pause()
            return
        if not volumes:
            print("No fue posible consultar unidades.")
        for volume in volumes:
            print(f"\n{volume['mountpoint']}")
            print(
                f"  Total: {volume['total_gb']:.2f} GB | "
                f"Usado: {volume['used_gb']:.2f} GB | "
                f"Libre: {volume['free_gb']:.2f} GB"
            )
            print(f"  Uso: {volume['used_percent']:.1f}%")
            if professional:
                self._line("Sistema de archivos", volume["filesystem"])
                for directory in volume["largest_directories"]:
                    print(
                        f"  Directorio aprox. {directory['size_bytes'] / 1024 ** 2:.1f} MB: "
                        f"{directory['path']}"
                    )
        self._persist("Almacenamiento", volumes)
        self._pause()

    def _show_recommended(self, professional):
        self.screens.mostrar_encabezado()
        result = self._collect(
            self.diagnostics.recommended_maintenance,
            professional=professional,
        )
        print("MANTENIMIENTO RECOMENDADO")
        print("─" * 48)
        if result is None:
            self._pause()
            return
        self.last_result = result
        self.screens.estado = result.severity
        for check in result.checks:
            if check.status is False:
                continue
            marker = check.severity.display
            print(f"{marker} {check.name}: {check.description}")
        for finding in result.recommendations:
            print(f"{finding.severity.display} {finding.title}")
            if finding.code == "MAINTENANCE_DISK_LOW_SPACE":
                print(f"→ {finding.description}")
            if finding.recommendation:
                print(f"→ {finding.recommendation}")
            if professional:
                print(f"  Código: {finding.code}")
                print(f"  Evidencia: {finding.evidence}")
        print("\nEstas recomendaciones no ejecutan acciones.")
        if professional:
            print(f"Fecha: {result.timestamp} | Equipo: {result.computer}")
        self._persist("Mantenimiento recomendado", result.to_dict())
        self._pause()

    def _confirm(self, prompt):
        value = input(prompt).strip()
        return value if value == CONFIRMATION_TOKEN else ""

    def _present_action(self, result):
        if result is None:
            return
        self._line("Acción", result.action)
        self._line("Resultado", result.result)
        self._line("Riesgo", result.risk)
        self._line("Equipo", result.computer)
        self._line("Usuario", result.user)
        self._line("Fecha", result.timestamp)
        if result.target is not None:
            self._line("Destino", result.target)
        if result.error:
            self._line("Error", result.error)
        if result.details:
            self._line("Detalles", result.details)
        self._persist(f"Acción: {result.action}", result.to_dict())

    def _persist(self, title, data):
        if not self.history_logger:
            return
        try:
            self.history_logger.iniciar_sesion()
            self.history_logger.registrar(title, data)
        except Exception:
            logger.exception("No se pudo guardar resultado de mantenimiento")

    @staticmethod
    def _line(label, value, unit="", indent="  "):
        if value is None or value == "":
            value = "No disponible"
        elif unit:
            value = f"{value} {unit}"
        print(f"{indent}{label:<24} {value}")

    @staticmethod
    def _pause():
        pausar()


def _selected(items, choice):
    try:
        index = int(choice) - 1
    except (TypeError, ValueError):
        return None
    return items[index] if 0 <= index < len(items) else None


def _format(value):
    return "—" if value is None else f"{value:.1f}"


def _without_files(inventory):
    return {
        key: value for key, value in inventory.items()
        if key != "files"
    }
