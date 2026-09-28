"""CMD menus for structured network checks and confirmed network actions."""

import logging

from core.actions import ActionRisk
from core.permissions import solicitar_autorizacion
from core.severity import Severity
from modules.red import (
    DIAGNOSTIC_DOMAINS,
    NetworkDiagnostics,
    _is_network_adapter,
)
from ui.components import pausar


logger = logging.getLogger("hardware_diagnostico")


class NetworkMenu:
    def __init__(self, screens, history_logger=None):
        self.screens = screens
        self.history_logger = history_logger
        self.last_result = None

    def mostrar(self, professional=False):
        while True:
            self.screens.mostrar_encabezado()
            self._menu(professional)
            option = input("\nSelecciona una opción: ").strip()
            if option == "0":
                return
            if option == "1":
                self._show_adapters(professional)
            elif option == "2":
                self._show_configuration(professional)
            elif option == "3":
                self._show_gateway(professional)
            elif option == "4":
                self._show_dns(professional)
            elif option == "5":
                self._show_internet(professional)
            elif option == "6":
                self._show_ping(professional)
            elif option == "7":
                self._show_traceroute(professional)
            elif option == "8":
                self._show_automatic(professional)
            elif option == "9":
                self._renew_ip()
            elif option == "10" and professional:
                self._reset_network()
            else:
                print("Opción inválida o no disponible en Modo Normal.")
                pausar()

    @staticmethod
    def _menu(professional):
        print("╔════════════════════════════════════════════╗")
        print("║          DIAGNÓSTICO DE RED                ║")
        print("╚════════════════════════════════════════════╝")
        options = (
            ("1", "Adaptadores de red"),
            ("2", "Configuración IP"),
            ("3", "Gateway"),
            ("4", "DNS"),
            ("5", "Conectividad a Internet"),
            ("6", "Ping"),
            ("7", "Traceroute"),
            ("8", "Diagnóstico automático"),
            ("9", "Renovar configuración IP"),
        )
        for number, label in options:
            print(f"[{number}] {label}")
        if professional:
            print("[10] Restablecimiento de red")
        print("[0] Volver")

    def _collect(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception:
            logger.exception("Error no controlado durante el diagnóstico de red")
            print("No fue posible obtener esta información.")
            return None

    def _show_adapters(self, professional):
        self.screens.mostrar_encabezado()
        adapters = self._collect(NetworkDiagnostics().get_adapters)
        print("ADAPTADORES")
        print("─" * 40)
        if not adapters:
            print("No fue posible obtener adaptadores.")
            pausar()
            return
        connected = []
        for index, adapter in enumerate(adapters, 1):
            print(f"\n[{index}] {adapter.name}")
            print(f"  Estado: {adapter.status}")
            self._line("Tipo", adapter.adapter_type)
            if (
                adapter.is_up
                and adapter.is_physical is not False
                and _is_network_adapter(adapter)
            ):
                connected.append(adapter)
            if professional:
                self._line("Descripción", adapter.description)
                self._line("Velocidad", adapter.speed_mbps, "Mbps")
                self._line("MAC", adapter.mac_address)
                self._line("IPv4", ", ".join(adapter.ipv4) or None)
                self._line("IPv6", ", ".join(adapter.ipv6) or None)
                self._line("DHCP", adapter.dhcp_enabled)
                self._line("Gateway", ", ".join(adapter.gateways) or None)
                self._line("DNS", ", ".join(adapter.dns_servers) or None)
                if adapter.adapter_type == "Wi-Fi":
                    self._line("SSID", adapter.ssid)
                    self._line("BSSID", adapter.bssid)
                    self._line("Señal", adapter.signal_percent, "%")
                    self._line("Canal", adapter.channel)
                    self._line("Radio", adapter.wifi_radio)
                self._line("Fuente", adapter.source)
        if connected:
            print(f"\nEstado general: ✓ Adaptador {connected[0].name} conectado")
        else:
            print("\nEstado general: ⚠ No se detectó adaptador conectado")
        self._pause()

    def _show_configuration(self, professional):
        self.screens.mostrar_encabezado()
        configuration = self._collect(NetworkDiagnostics().get_configuration)
        print("CONFIGURACIÓN IP")
        print("─" * 40)
        if not configuration:
            self._pause()
            return
        self._line("Hostname", configuration.hostname)
        self._line("Gateway predeterminado", configuration.default_gateway)
        self._line("DNS", ", ".join(configuration.dns_servers) or None)
        if configuration.apipa_addresses:
            self._line(
                "APIPA detectada",
                ", ".join(configuration.apipa_addresses),
            )
            print("⚠ Posible problema de asignación DHCP; la dirección no confirma la causa.")
        self._line(
            "IPv4 válida detectada",
            "Sí" if configuration.valid_ipv4 else "No",
        )
        for adapter in configuration.adapters:
            if (
                not adapter.is_up
                or adapter.is_physical is False
                or not _is_network_adapter(adapter)
            ):
                continue
            print(f"\n{adapter.name}")
            self._line("IPv4", ", ".join(adapter.ipv4) or None)
            if professional:
                self._line("IPv6", ", ".join(adapter.ipv6) or None)
                self._line("Máscara", ", ".join(adapter.subnet_masks) or None)
                self._line(
                    "Prefijos",
                    ", ".join(map(str, adapter.prefix_lengths)) or None,
                )
                self._line(
                    "DHCP",
                    _yes_no(adapter.dhcp_enabled),
                )
                self._line("Servidor DHCP", adapter.dhcp_server)
                self._line("DNS", ", ".join(adapter.dns_servers) or None)
        self._pause()

    def _show_gateway(self, professional):
        self.screens.mostrar_encabezado()
        diagnostic = NetworkDiagnostics()
        configuration = self._collect(diagnostic.get_configuration)
        if not configuration:
            self._pause()
            return
        gateway = self._collect(diagnostic.gateway_test, configuration)
        print("GATEWAY")
        print("─" * 40)
        if not gateway:
            self._pause()
            return
        self._line("Gateway", gateway.address)
        if gateway.reachable is None:
            self._line("Ping", "No se pudo comprobar (gateway no disponible)")
        else:
            self._line("Ping", "✓ Responde" if gateway.reachable else "⚠ No responde")
        if gateway.ping:
            self._show_ping_result(gateway.ping, professional)
        if gateway.reachable:
            print("Estado: ✓ NORMAL")
        elif gateway.reachable is False:
            print(
                "\n⚠ El equipo tiene configuración de red, pero no fue posible "
                "alcanzar el gateway."
            )
            print("Algunos routers filtran ICMP; el resultado no confirma por sí solo una falla.")
        self._pause()

    def _show_dns(self, professional):
        self.screens.mostrar_encabezado()
        configuration = self._collect(NetworkDiagnostics().get_configuration)
        if not configuration:
            self._pause()
            return
        domain = input(
            f"Dominio para resolver (ENTER = {DIAGNOSTIC_DOMAINS[0]}): "
        ).strip() or DIAGNOSTIC_DOMAINS[0]
        result = self._collect(
            NetworkDiagnostics().dns_test,
            domain,
            configuration.dns_servers,
        )
        print("\nDNS")
        print("─" * 40)
        if not result:
            self._pause()
            return
        self._line("Servidores configurados", ", ".join(result.configured_servers) or None)
        self._line("Dominio", result.domain)
        self._line(
            "Resolución",
            "✓ Correcta" if result.resolution_succeeded else "✖ Fallida",
        )
        self._line("Direcciones", ", ".join(result.resolved_addresses) or None)
        if professional:
            for server, responded in result.server_responses.items():
                self._line(
                    f"Respuesta DNS {server}",
                    "✓ Respondió" if responded else "✖ Sin respuesta",
                )
            self._line("Error", result.error)
            self._line("Fuente", result.source)
            self._line("Timestamp", result.timestamp)
        self._pause()

    def _show_internet(self, professional):
        self.screens.mostrar_encabezado()
        result = self._collect(NetworkDiagnostics().internet_test)
        print("CONECTIVIDAD A INTERNET")
        print("─" * 40)
        if not result:
            self._pause()
            return
        self._line(
            "Conectividad externa",
            "✓ Disponible" if result["reachable"] else "⚠ No confirmada",
        )
        self._line("Destino probado", result["probe"])
        if professional:
            self._line("Error", result["error"])
            self._line("Fuente", "TCP socket")
        self._pause()

    def _show_ping(self, professional):
        self.screens.mostrar_encabezado()
        destination = input("Destino (IP o hostname): ").strip()
        result = self._collect(NetworkDiagnostics().ping, destination)
        print("\nPING")
        print("─" * 40)
        if result:
            self._show_ping_result(result, professional)
        self._pause()

    def _show_ping_result(self, result, professional):
        self._line("Destino", result.destination)
        self._line("Enviados", result.packets_sent)
        self._line("Recibidos", result.packets_received)
        self._line("Perdidos", result.packets_lost)
        self._line(
            "Pérdida",
            result.packet_loss_percent if result.packets_sent else None,
            "%",
        )
        self._line("Mínimo", result.minimum_ms, "ms")
        self._line("Máximo", result.maximum_ms, "ms")
        self._line("Promedio", result.average_ms, "ms")
        if result.error and result.packets_sent == 0:
            print(f"Estado: ⚠ No fue posible ejecutar ping: {result.error}")
        elif result.packets_received == 0:
            print("Estado: ⚠ No respondió; el destino puede filtrar ICMP.")
        elif result.packet_loss_percent:
            print("Estado: ⚠ Pérdida de paquetes detectada hacia este destino.")
        else:
            print("Estado: ✓ NORMAL")
        for finding in result.findings:
            print(f"{finding.severity.display}: {finding.title}")
            print(f"  Evidencia: {finding.evidence}")
            if finding.recommendation:
                print(f"  Recomendación: {finding.recommendation}")
        if professional:
            self._line("Muestras (ms)", result.samples_ms or None)
            self._line("Error", result.error)
            self._line("Fuente", result.source)
            self._line("Timestamp", result.timestamp)

    def _show_traceroute(self, professional):
        self.screens.mostrar_encabezado()
        destination = input("Destino (IP o hostname): ").strip()
        result = self._collect(NetworkDiagnostics().traceroute, destination)
        print("\nTRACEROUTE")
        print("─" * 40)
        if not result:
            self._pause()
            return
        self._line("Destino", result["destination"])
        for hop in result["hops"]:
            print(f"{hop['hop']:<5} {hop['route']}")
        if not result["hops"]:
            print("No fue posible obtener saltos.")
        if professional:
            self._line("Comando", "tracert -d")
            self._line("Error", result["error"])
            self._line("Timestamp", result["timestamp"])
        print("Un salto * * * puede filtrar ICMP y no confirma una falla.")
        self._pause()

    def _show_automatic(self, professional):
        self.screens.mostrar_encabezado()
        print("DIAGNÓSTICO DE RED\n")
        result = self._collect(NetworkDiagnostics().automatic_diagnostic)
        if not result:
            self._pause()
            return
        self.last_result = result
        self._persist("Diagnóstico de red", result.to_dict())
        self.screens.estado = result.severity
        for check in result.checks:
            icon = check.severity.display if check.status is not None else "ℹ SIN DATOS"
            print(f"[{icon}] {check.name}")
        connected = [
            adapter for adapter in result.adapters
            if (
                adapter.is_up
                and adapter.is_physical is not False
                and _is_network_adapter(adapter)
            )
        ]
        if connected:
            adapter = connected[0]
            self._line("Adaptador", adapter.name)
            self._line("IPv4", ", ".join(adapter.ipv4) or None)
            self._line("Gateway", result.configuration.default_gateway)
            self._line(
                "DNS",
                ", ".join(result.configuration.dns_servers) or None,
            )
        if result.dns.resolved_addresses:
            self._line(
                "Resolución DNS",
                ", ".join(result.dns.resolved_addresses),
            )
        self._line(
            "Internet",
            "Disponible" if result.internet_reachable is True
            else "No confirmado" if result.internet_reachable is False
            else None,
        )
        if result.ping:
            self._line("Latencia media al gateway", result.ping.average_ms, "ms")
            self._line("Pérdida al gateway", result.ping.packet_loss_percent, "%")
        print("\n" + "─" * 44)
        print("RESULTADO")
        print(f"{result.severity.display} {result.diagnosis}")
        print(f"Evidencia: {result.findings[0].description if result.findings else 'Sin hallazgos.'}")
        if result.recommendation:
            print(f"Recomendación: {result.recommendation}")
        if professional:
            self._line("Timestamp", result.timestamp)
            self._line("Fuente", result.source)
            for finding in result.findings:
                print(f"\n{finding.code} | {finding.component}")
                print(f"  Severidad: {finding.severity.display}")
                print(f"  Evidencia: {finding.evidence}")
                self._line("Fuente", finding.source, indent="    ")
                self._line("Confianza", finding.confidence, indent="    ")
                self._line("Regla", finding.rule_id, indent="    ")
            for adapter in result.adapters:
                print(f"\nInterfaz: {adapter.name}")
                self._line("MAC", adapter.mac_address, indent="  ")
                self._line("IPv4", ", ".join(adapter.ipv4) or None, indent="  ")
                self._line("IPv6", ", ".join(adapter.ipv6) or None, indent="  ")
                self._line("Gateway", ", ".join(adapter.gateways) or None, indent="  ")
                self._line("DNS", ", ".join(adapter.dns_servers) or None, indent="  ")
                self._line("DHCP", _yes_no(adapter.dhcp_enabled), indent="  ")
                self._line("SSID", adapter.ssid, indent="  ")
                self._line("BSSID", adapter.bssid, indent="  ")
                self._line("Señal", adapter.signal_percent, "%", indent="  ")
                self._line("Velocidad", adapter.speed_mbps, "Mbps", indent="  ")
        self._pause()

    def diagnostico_automatico(self, professional=False):
        return self._show_automatic(professional)

    def _renew_ip(self):
        self.screens.mostrar_encabezado()
        print("╔════════════════════════════════════════════╗")
        print("║       RENOVAR CONFIGURACIÓN IP             ║")
        print("╚════════════════════════════════════════════╝")
        print("Esta operación puede interrumpir temporalmente la conexión de red.")
        choice = input("\n¿Deseas continuar? [1] Sí  [0] Cancelar: ").strip()
        if choice != "1":
            print("Operación cancelada.")
            self._pause()
            return
        approved = solicitar_autorizacion(
            ActionRisk.CONFIRMATION,
            "Renovar la configuración IP mediante ipconfig /release y /renew.",
            input_func=lambda _prompt: "s",
        )
        if not approved:
            self._pause()
            return
        result = self._collect(NetworkDiagnostics().renew_ip_configuration)
        if result:
            print(
                "\n✓ Configuración renovada correctamente."
                if result.success
                else "\n✖ No fue posible renovar la configuración."
            )
            for output in result.outputs:
                if output["return_code"] != 0:
                    self._line("Error", output.get("error") or output.get("stderr"))
            self._persist("Acción: renovar IP", _safe_action_data(result))
        self._pause()

    def _reset_network(self):
        self.screens.mostrar_encabezado()
        print("╔════════════════════════════════════════════╗")
        print("║          RESTABLECIMIENTO DE RED           ║")
        print("╚════════════════════════════════════════════╝")
        print(
            "Restablecerá Winsock y TCP/IP. Puede requerir privilegios "
            "de administrador y un reinicio de Windows."
        )
        approved = solicitar_autorizacion(
            ActionRisk.PROFESSIONAL,
            "Restablecer Winsock y TCP/IP. La operación puede requerir reiniciar Windows.",
            modo_profesional=True,
            input_func=input,
        )
        if not approved:
            print("Operación cancelada.")
            self._pause()
            return
        result = self._collect(NetworkDiagnostics().reset_network)
        if result:
            if result.success:
                print(
                    "\n✓ Restablecimiento ejecutado. Reinicia Windows para completar los cambios."
                )
            elif result.requires_restart:
                print(
                    "\n⚠ Restablecimiento parcial. Reinicia Windows y revisa el registro."
                )
            else:
                print("\n✖ No fue posible completar el restablecimiento.")
            for output in result.outputs:
                if output["return_code"] != 0:
                    self._line("Error", output.get("error") or output.get("stderr"))
            self._persist("Acción: restablecer red", _safe_action_data(result))
        self._pause()

    def _persist(self, title, data):
        if not self.history_logger:
            return
        try:
            self.history_logger.iniciar_sesion()
            self.history_logger.registrar(title, data)
        except Exception:
            logger.exception("No se pudo guardar el resultado de red en el historial")

    @staticmethod
    def _line(label, value, unit="", indent="  "):
        if value is None or value == "":
            value = "No disponible"
        elif unit:
            value = f"{value} {unit}"
        print(f"{indent}{label:<28} {value}")

    def _pause(self):
        pausar()


def _yes_no(value):
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return None


def _safe_action_data(result):
    return {
        "action": result.action,
        "success": result.success,
        "commands": result.commands,
        "user": result.user,
        "timestamp": result.timestamp,
        "requires_restart": result.requires_restart,
        "results": [
            {
                "command": item["command"],
                "return_code": item["return_code"],
                "error": item["error"],
            }
            for item in result.outputs
        ],
    }
