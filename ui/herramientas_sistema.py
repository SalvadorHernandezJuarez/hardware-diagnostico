"""CMD interface for safe system information and predefined utilities."""

import logging

from modules.herramientas_sistema import (
    ADMIN_TOOLS,
    DIAGNOSTIC_COMMANDS,
    SystemToolsDiagnostics,
)
from ui.components import pausar


logger = logging.getLogger("hardware_diagnostico")


class SystemToolsMenu:
    def __init__(self, screens, history_logger=None, diagnostics=None):
        self.screens = screens
        self.history_logger = history_logger
        self.diagnostics = diagnostics or SystemToolsDiagnostics()
        self.last_result = None

    def mostrar(self, professional=False):
        if not professional:
            logger.warning("Herramientas del sistema solicitadas fuera del modo profesional")
            print("Herramientas del sistema solo están disponibles en Modo Profesional.")
            pausar()
            return
        handlers = {
            "1": self._windows_info,
            "2": self._environment,
            "3": self._processes,
            "4": self._services,
            "5": self._drivers,
            "6": self._devices,
            "7": self._network,
            "8": self._events,
            "9": self._commands,
            "10": self._installed_software,
            "11": self._admin_tools,
        }
        while True:
            self.screens.mostrar_encabezado()
            self._menu(professional)
            option = input("\nSelecciona una opción: ").strip()
            if option == "0":
                return
            handler = handlers.get(option)
            if handler:
                handler(professional)
            else:
                print("Opción inválida.")
                pausar()

    @staticmethod
    def _menu(professional=False):
        print("╔════════════════════════════════════╗")
        print("║       HERRAMIENTAS DEL SISTEMA     ║")
        print("╚════════════════════════════════════╝")
        options = (
            ("1", "Información de Windows"),
            ("2", "Variables de entorno"),
            ("3", "Procesos y tareas"),
            ("4", "Servicios del sistema"),
            ("5", "Controladores"),
            ("6", "Dispositivos"),
            ("7", "Información de red"),
            ("8", "Eventos recientes"),
            ("9", "Comandos de diagnóstico"),
            ("10", "Software instalado y versiones"),
        )
        for number, label in options:
            print(f"[{number}] {label}")
        if professional:
            print("[11] Consola administrativa")
        print("[0] Volver")

    def _windows_info(self, professional):
        report = self._collect(self.diagnostics.windows_info)
        if report:
            data = report.data
            print("INFORMACIÓN DE WINDOWS\n" + "─" * 48)
            for key, label in (
                ("edition", "Edición"),
                ("version", "Versión"),
                ("build", "Build"),
                ("architecture", "Arquitectura"),
                ("computer_name", "Equipo"),
                ("user", "Usuario"),
                ("install_date", "Fecha de instalación"),
                ("last_boot", "Último arranque"),
                ("uptime_seconds", "Tiempo activo (s)"),
            ):
                self._line(label, data.get(key))
            self._present(report, professional, persist=True)
        self._pause()

    def _environment(self, professional):
        report = self._collect(self.diagnostics.environment_variables)
        if not report:
            self._pause()
            return
        print("VARIABLES DE ENTORNO\n" + "─" * 48)
        for name, value in report.data["variables"].items():
            self._line(name, value)
        query = input(
            "\nBuscar una variable específica (ENTER para volver): "
        ).strip()
        if query:
            report = self._collect(
                self.diagnostics.environment_variables,
                query,
            )
            if report:
                for name, value in report.data["variables"].items():
                    self._line(name, value)
        print("Las variables se consultan en modo de solo lectura.")
        # Environment values are deliberately not written to diagnostic history.
        self._present(report, professional, persist=False)
        self._pause()

    def _processes(self, professional):
        order = input("Ordenar por [C]PU o [M]emoria (M): ").strip().casefold()
        sort_by = "cpu" if order == "c" else "memory"
        report = self._collect(self.diagnostics.processes, sort_by)
        if not report:
            self._pause()
            return
        records = report.data["processes"]
        print(f"PROCESOS — orden: {'CPU' if sort_by == 'cpu' else 'memoria'}")
        print("─" * 100)
        if not records:
            print("No hay procesos disponibles.")
        for index, process in enumerate(records[:60 if professional else 30], 1):
            self._line(
                f"[{index}] PID / Nombre",
                f"{process.get('pid', 'DESCONOCIDO')} / "
                f"{process.get('name') or 'DESCONOCIDO'}",
            )
            self._line("CPU / RAM", f"{_unknown(process.get('cpu_percent'))}% / "
                       f"{_unknown(process.get('memory_mb'))} MB", indent="    ")
            self._line("Usuario", process.get("user"), indent="    ")
            self._line("Ruta", process.get("path"), indent="    ")
        self._present(report, professional, persist=False)
        if records:
            choice = input(
                "\nNúmero de proceso a finalizar (0 = volver): "
            ).strip()
            if choice.isdigit() and int(choice) > 0:
                index = int(choice) - 1
                if index >= len(records[:60 if professional else 30]):
                    print("Selección fuera de rango.")
                else:
                    process = records[index]
                    token = input(
                        f"Se solicitará a Mantenimiento finalizar "
                        f"{process.get('name')} (PID {process.get('pid')}). "
                        "Escribe CONFIRMAR: "
                    ).strip()
                    action = self.diagnostics.maintenance.terminate_process(
                        process.get("pid"), token
                    )
                    self._line("Resultado", action.result)
                    self._line("Error", action.error)
                    self._persist("Herramientas - acción de proceso", action.to_dict())
        self._pause()

    def _services(self, professional):
        report = self._collect(self.diagnostics.services)
        if report:
            print("SERVICIOS DEL SISTEMA\n" + "─" * 76)
            services = report.data.get("services", [])
            if not services:
                print("Servicios no disponibles.")
            for service in services:
                self._line(
                    service.get("DisplayName") or service.get("Name") or "DESCONOCIDO",
                    f"{service.get('State') or 'DESCONOCIDO'} | "
                    f"Inicio: {service.get('StartMode') or 'DESCONOCIDO'}",
                )
                if professional:
                    self._line("Nombre", service.get("Name"), indent="    ")
                self._line("Descripción", service.get("Description"), indent="    ")
            print("\nPara modificar servicios, utiliza Mantenimiento.")
            self._present(report, professional, persist=True)
        self._pause()

    def _drivers(self, professional):
        report = self._collect(self.diagnostics.drivers)
        if report:
            print("CONTROLADORES\n" + "─" * 76)
            records = report.data.get("drivers", [])
            if not report.data.get("available"):
                print("No fue posible obtener la información de controladores.")
            elif not records:
                print("No se detectaron controladores o la consulta no devolvió datos.")
            for driver in records[:100 if professional else 40]:
                self._line("Nombre", driver.get("DeviceName"))
                self._line("Fabricante", driver.get("Manufacturer"), indent="    ")
                self._line("Versión / fecha",
                           f"{_unknown(driver.get('DriverVersion'))} / "
                           f"{_unknown(driver.get('DriverDate'))}", indent="    ")
                self._line("Estado", driver.get("State"), indent="    ")
                if professional:
                    self._line("INF", driver.get("InfName"), indent="    ")
                    self._line("Firmado", driver.get("IsSigned"), indent="    ")
            self._present(report, professional, persist=True)
        self._pause()

    def _devices(self, professional):
        report = self._collect(self.diagnostics.devices)
        if report:
            print("DISPOSITIVOS\n" + "─" * 76)
            records = report.data.get("devices", [])
            if not report.data.get("available"):
                print("No fue posible consultar los dispositivos.")
            for device in records[:100 if professional else 40]:
                status = device.get("Status") or "DESCONOCIDO"
                error_code = device.get("ConfigManagerErrorCode")
                issue = (
                    error_code not in (None, 0, "0")
                    or str(status).casefold() in (
                        "error", "failed", "pred fail", "non-operational",
                        "nonoperational", "lost communication",
                    )
                )
                if str(error_code) == "22":
                    status = "Deshabilitado"
                elif issue:
                    status = f"Problema (código {error_code})"
                self._line(
                    device.get("Name") or "DESCONOCIDO",
                    f"{'⚠' if issue else '•'} {status}",
                )
                self._line("Fabricante / tipo",
                           f"{_unknown(device.get('Manufacturer'))} / "
                           f"{_unknown(device.get('PNPClass'))}", indent="    ")
                if professional:
                    self._line("Código de configuración",
                               _unknown(error_code), indent="    ")
            for finding in report.findings[1:]:
                print(f"\n{finding.severity.display} {finding.title}")
                print(f"  {finding.description}")
                if finding.recommendation:
                    print(f"  {finding.recommendation}")
            self._present(report, professional, persist=True)
        self._pause()

    def _network(self, professional):
        report = self._collect(self.diagnostics.network_info)
        if report:
            print("INFORMACIÓN DE RED\n" + "─" * 76)
            self._line("Equipo", report.data.get("hostname"))
            for adapter in report.data.get("adapters", []):
                print(f"\n{adapter['name']}")
                for key, label in (
                    ("type", "Tipo"),
                    ("status", "Estado"),
                    ("mac", "MAC"),
                    ("ipv4", "IPv4"),
                    ("ipv6", "IPv6"),
                    ("gateway", "Gateway"),
                    ("dns", "DNS"),
                ):
                    value = adapter.get(key)
                    if isinstance(value, list):
                        value = ", ".join(str(item) for item in value)
                    self._line(label, value, indent="    ")
            self._present(report, professional, persist=True)
        self._pause()

    def _events(self, professional):
        report = self._collect(self.diagnostics.recent_events)
        if report:
            print("EVENTOS RECIENTES (ÚLTIMOS 7 DÍAS)\n" + "─" * 76)
            events = report.data.get("events", [])
            if not report.data.get("available"):
                print("No fue posible consultar eventos.")
            if not events and report.data.get("available"):
                print("No se encontraron eventos coincidentes.")
            for event in events:
                self._line(
                    f"{event.get('Date') or 'DESCONOCIDO'} | "
                    f"{event.get('LevelDisplayName') or 'DESCONOCIDO'}",
                    f"{event.get('ProviderName') or 'DESCONOCIDO'} "
                    f"(ID {event.get('Id') or 'DESCONOCIDO'})",
                )
                self._line("Mensaje", event.get("Message"), indent="    ")
            self._present(report, professional, persist=True)
        self._pause()

    def _installed_software(self, professional):
        report = self._collect(self.diagnostics.installed_software)
        if report:
            print("SOFTWARE INSTALADO\n" + "─" * 76)
            software = report.data.get("software", [])
            if not report.data.get("available"):
                print("No fue posible consultar el software instalado.")
            elif not software:
                print("Windows no reportó aplicaciones registradas.")
            else:
                print(f"Aplicaciones encontradas: {report.data.get('count', len(software))}")
                for app in software:
                    self._line("Nombre", app.get("Name"))
                    self._line("Versión", app.get("Version"))
                    self._line("Editor", app.get("Publisher"))
                    if professional:
                        self._line("Fecha de instalación", app.get("InstallDate"))
                        self._line("Ubicación", app.get("InstallLocation"))
                    print()
            self._present(report, professional, persist=False)
        self._pause()

    def _commands(self, professional):
        while True:
            self.screens.mostrar_encabezado()
            print("COMANDOS DE DIAGNÓSTICO")
            print("─" * 48)
            keys = list(DIAGNOSTIC_COMMANDS)
            for index, key in enumerate(keys, 1):
                print(f"[{index}] {DIAGNOSTIC_COMMANDS[key]['label']}")
            print("[0] Volver")
            choice = input("\nSelecciona un comando: ").strip()
            if choice == "0":
                return
            if not choice.isdigit() or not 1 <= int(choice) <= len(keys):
                print("Opción inválida.")
                pausar()
                continue
            command_id = keys[int(choice) - 1]
            self._run_command(command_id, professional)

    def _run_command(self, command_id, professional):
        spec = DIAGNOSTIC_COMMANDS[command_id]
        result = self._collect(
            self.diagnostics.run_diagnostic_command,
            command_id,
        )
        if result is None:
            self._pause()
            return
        print(f"{spec['label'].upper()}\n" + "─" * 64)
        self._line("Comando", " ".join(result["command"]))
        self._line("Código de retorno", result["return_code"])
        self._line("Tiempo", result["duration_seconds"], unit="s")
        self._line("Error", result.get("error") or result.get("stderr"))
        finding = result.get("finding", {})
        self._line("Código diagnóstico", finding.get("code"))
        if finding.get("recommendation"):
            self._line("Recomendación", finding["recommendation"])
        output = result.get("stdout") or "(sin salida)"
        max_output = 40000 if professional else 12000
        print("\nSalida:\n" + output[:max_output])
        if len(output) > max_output:
            print("\n[Salida truncada en pantalla; la consulta terminó.]")
        self._persist(
            f"Comando de diagnóstico: {command_id}",
            {**result, "stdout": output[:40000], "stderr": result.get("stderr", "")[:4000]},
        )
        self._pause()

    def _admin_tools(self, professional):
        while True:
            self.screens.mostrar_encabezado()
            print("CONSOLA ADMINISTRATIVA — HERRAMIENTAS PREDEFINIDAS")
            print("─" * 64)
            ids = list(ADMIN_TOOLS)
            for index, tool_id in enumerate(ids, 1):
                print(f"[{index}] {ADMIN_TOOLS[tool_id][0]}")
            print("[0] Volver")
            choice = input("\nSelecciona una herramienta: ").strip()
            if choice == "0":
                return
            if not choice.isdigit() or not 1 <= int(choice) <= len(ids):
                print("Opción inválida.")
                pausar()
                continue
            tool_id = ids[int(choice) - 1]
            label = ADMIN_TOOLS[tool_id][0]
            token = input(
                f"Se abrirá {label}. Solo se inicia la herramienta nativa; "
                "no se eleva ni se ejecuta un comando libre. "
                "Escribe CONFIRMAR: "
            ).strip()
            result = self._collect(
                self.diagnostics.launch_admin_tool,
                tool_id,
                professional,
                token,
            )
            if result:
                self._line("Herramienta", result.get("tool"))
                self._line(
                    "Resultado",
                    "Iniciada" if result.get("success") else "No iniciada",
                )
                self._line("Error", result.get("error"))
                self._persist("Herramienta administrativa", result)
            self._pause()

    def _collect(self, operation, *args):
        try:
            result = operation(*args)
            self.last_result = result
            finding = getattr(result, "finding", None)
            if finding is not None:
                self.screens.estado = finding.severity
            return result
        except Exception:
            logger.exception("Falló una consulta de herramientas del sistema")
            print("No fue posible obtener esta información.")
            return None

    def _present(self, report, professional, persist):
        finding = report.finding
        print(f"\n{finding.severity.display} {finding.title}")
        if professional:
            print(f"Código: {finding.code}")
            print(f"Componente: {finding.component}")
            print(f"Fuente: {report.source}")
            print(f"Fecha: {finding.timestamp}")
            if finding.recommendation:
                print(f"Recomendación: {finding.recommendation}")
        if persist:
            self._persist(finding.title, report.to_dict())

    def _persist(self, title, data):
        if not self.history_logger:
            return
        try:
            self.history_logger.iniciar_sesion()
            self.history_logger.registrar(title, data)
        except Exception:
            logger.exception("No se pudo guardar el resultado de herramientas")

    @staticmethod
    def _line(label, value, unit="", indent="  "):
        value = _unknown(value)
        if unit and value != "DESCONOCIDO":
            value = f"{value} {unit}"
        print(f"{indent}{label:<28} {value}")

    @staticmethod
    def _pause():
        pausar()


def _unknown(value):
    if value is None or value == "":
        return "DESCONOCIDO"
    if isinstance(value, list):
        return ", ".join(_unknown(item) for item in value) if value else "DESCONOCIDO"
    return str(value)
