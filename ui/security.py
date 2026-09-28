"""CMD interface for read-only Windows security diagnostics."""

import logging

from core.severity import Severity
from modules.security import SECURITY_SECTIONS, SecurityAuditor
from ui.components import pausar


logger = logging.getLogger("hardware_diagnostico")

SECTION_LABELS = {
    "firewall": "Firewall",
    "defender": "Windows Defender",
    "bitlocker": "BitLocker",
    "windows_update": "Windows Update",
    "users": "Usuarios",
    "services": "Servicios importantes",
    "configuration": "Configuración de seguridad",
}


class SecurityMenu:
    def __init__(self, screens, history_logger=None):
        self.screens = screens
        self.history_logger = history_logger
        self.last_result = None

    def mostrar(self, professional=False):
        while True:
            self.screens.mostrar_encabezado()
            self._show_menu()
            option = input("\nSelecciona una opción: ").strip()
            if option == "0":
                return
            if option == "8":
                self._show_audit(professional)
                continue
            if option in ("1", "2", "3", "4", "5", "6", "7"):
                self._show_section(
                    SECURITY_SECTIONS[int(option) - 1],
                    professional,
                )
                continue
            print("Opción inválida.")
            pausar()

    @staticmethod
    def _show_menu():
        print("╔════════════════════════════════════════════╗")
        print("║          SEGURIDAD DE WINDOWS              ║")
        print("╚════════════════════════════════════════════╝")
        for number, label in (
            ("1", "Firewall"),
            ("2", "Windows Defender"),
            ("3", "BitLocker"),
            ("4", "Windows Update"),
            ("5", "Usuarios"),
            ("6", "Servicios importantes"),
            ("7", "Configuración de seguridad"),
            ("8", "Auditoría completa"),
            ("0", "Volver"),
        ):
            print(f"[{number}] {label}")

    def _show_section(self, section, professional):
        self.screens.mostrar_encabezado()
        result = self._collect((section,))
        if result:
            self._present(result, professional, (section,))
        self._pause()

    def _show_audit(self, professional):
        self.screens.mostrar_encabezado()
        print("AUDITORÍA DE SEGURIDAD\n")
        result = self._collect(SECURITY_SECTIONS)
        if result:
            self._present(result, professional, SECURITY_SECTIONS)
        self._pause()

    @staticmethod
    def _collect(sections):
        try:
            return SecurityAuditor().audit(sections)
        except Exception:
            logger.exception("Error durante la auditoría de seguridad")
            print("No fue posible completar esta comprobación.")
            return None

    def _present(self, result, professional, sections):
        self.last_result = result
        self.screens.estado = result.severity
        if len(sections) == 1:
            print(SECTION_LABELS[sections[0]].upper())
            print("─" * 40)

        shown_checks = self._checks_for_sections(result, sections)
        if len(sections) > 1:
            for check in result.checks:
                marker = check.severity.display if check.status is not None else "ℹ"
                suffix = " No disponible" if check.status is None else ""
                print(f"[{marker}] {check.name}{suffix}")
        else:
            for check in shown_checks:
                self._print_check(check)
        if professional:
            self._show_details(result, sections)

        findings = self._findings_for_sections(result, sections)
        if len(sections) == 1 and findings:
            print("\nHallazgos")
        for finding in findings:
            if finding.severity in (Severity.ALERT, Severity.CRITICAL):
                print(f"{finding.severity.display} {finding.title}")
                print(f"  Evidencia: {finding.description}")
                if finding.recommendation:
                    print(f"  Recomendación: {finding.recommendation}")
            elif professional:
                print(f"{finding.severity.display} {finding.title} [{finding.code}]")

        if len(sections) > 1:
            alerts = sum(
                finding.severity == Severity.ALERT for finding in result.findings
            )
            critical = sum(
                finding.severity == Severity.CRITICAL for finding in result.findings
            )
            print("\n" + "─" * 44)
            print("RESULTADO")
            print(result.severity.display)
            print(f"Alertas: {alerts}")
            print(f"Críticos: {critical}")
            if not professional:
                for finding in result.findings:
                    if finding.severity >= Severity.ALERT:
                        print(f"{finding.severity.display} {finding.title}")

        if professional:
            print(f"\nTimestamp: {result.timestamp}")
            print("Comandos / fuentes consultadas:")
            for command in result.commands:
                print(f"  - {command}")
            for finding in findings:
                print(
                    f"\n{finding.code} | {finding.severity.display} | "
                    f"{finding.component}"
                )
                print(f"  Evidencia: {finding.evidence}")
                if finding.recommendation:
                    print(f"  Recomendación: {finding.recommendation}")
        self._persist("Auditoría de seguridad", result.to_dict())

    @staticmethod
    def _checks_for_sections(result, sections):
        names = {
            "firewall": {"firewall"},
            "defender": {
                "windows defender", "protección en tiempo real",
                "firmas de defender",
            },
            "bitlocker": {"bitlocker"},
            "windows_update": {"windows update"},
            "users": {"usuarios", "administradores locales"},
            "services": {"servicios"},
            "configuration": {
                "firewall", "windows defender", "firmas de defender",
                "protección en tiempo real", "administradores locales",
                "bitlocker", "windows update", "usuarios", "servicios",
                "configuración de seguridad", "uac", "secure boot", "tpm",
            },
        }
        wanted = set().union(*(names[section] for section in sections))
        return [
            check for check in result.checks
            if check.name.casefold() in wanted
        ]

    @staticmethod
    def _findings_for_sections(result, sections):
        prefixes = {
            "firewall": ("SEC_FIREWALL",),
            "defender": (
                "SEC_DEFENDER", "SEC_REALTIME", "SEC_WINDOWS_DEFENDER",
            ),
            "bitlocker": ("SEC_BITLOCKER",),
            "windows_update": ("SEC_UPDATES",),
            "users": ("SEC_ADMIN", "SEC_ADDITIONAL", "SEC_USERS", "SEC_USUARIOS"),
            "services": (
                "SEC_SERVICES", "SEC_SERVICIOS",
                "SEC_SERVICIOS_IMPORTANTES",
            ),
            "configuration": (
                "SEC_UAC", "SEC_SECURE_BOOT", "SEC_TPM",
                "SEC_CONFIGURATION", "SEC_FIREWALL", "SEC_DEFENDER",
                "SEC_REALTIME", "SEC_BITLOCKER", "SEC_UPDATES",
                "SEC_CONFIGURACIÓN",
                "SEC_ADMIN", "SEC_ADDITIONAL", "SEC_USERS",
                "SEC_SERVICES", "SEC_SERVICIOS",
            ),
        }
        wanted = tuple(
            prefix for section in sections for prefix in prefixes[section]
        )
        return [
            finding for finding in result.findings
            if finding.code.startswith(wanted)
        ]

    @staticmethod
    def _print_check(check):
        if check.status is None:
            print(f"ℹ {check.name}: No disponible")
        else:
            print(f"{check.severity.display} {check.name}: {check.description}")

    def _show_details(self, result, sections):
        for section in sections:
            data = result.data.get(section, {})
            print(f"\n{SECTION_LABELS[section]} — evidencia")
            for key, value in data.items():
                if key in ("available", "error"):
                    continue
                print(f"  {key.replace('_', ' ').title()}: {value}")
            if data.get("error"):
                print(f"  Error: {data['error']}")
        if "configuration" in sections:
            important = {
                "firewall": "Firewall",
                "defender": "Windows Defender",
                "bitlocker": "BitLocker",
                "windows_update": "Windows Update",
                "users": "Usuarios",
            }
            check_by_name = {
                check.name.casefold(): check for check in result.checks
            }
            for section, check_name in important.items():
                check = check_by_name.get(check_name.casefold())
                state = (
                    "No disponible" if check is None or check.status is None
                    else check.description
                )
                print(f"  {SECTION_LABELS[section]}: {state}")
            users = result.data.get("users", {})
            if users.get("available"):
                current_user = users.get("current_user") or "No disponible"
                is_admin = users.get("current_is_admin")
                admin_state = (
                    "No disponible" if is_admin is None
                    else "Sí" if is_admin else "No"
                )
                print(f"  Usuario actual: {current_user}")
                print(f"  Usuario actual administrador: {admin_state}")
                if users.get("administrators_available"):
                    print(
                        "  Administradores locales: "
                        f"{users.get('administrators') or 'No disponible'}"
                    )
                else:
                    print("  Administradores locales: No disponible")

    def _persist(self, title, data):
        if not self.history_logger:
            return
        try:
            self.history_logger.iniciar_sesion()
            self.history_logger.registrar(title, data)
        except Exception:
            logger.exception("No se pudo guardar la auditoría en el historial")

    @staticmethod
    def _pause():
        pausar()
