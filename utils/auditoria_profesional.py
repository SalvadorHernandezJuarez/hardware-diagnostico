"""
utils/auditoria_profesional.py - Herramientas de diagnóstico para soporte técnico
"""

import platform
import socket
import subprocess
from datetime import datetime

import psutil


class AuditoriaProfesional:
    """Recopila información técnica de red y seguridad sin modificar el equipo."""

    @staticmethod
    def diagnostico_red() -> dict:
        interfaces = []
        for nombre, direcciones in psutil.net_if_addrs().items():
            ipv4 = []
            mac = ""
            for direccion in direcciones:
                if direccion.family == socket.AF_INET:
                    ipv4.append(direccion.address)
                elif getattr(psutil, "AF_LINK", object()) == direccion.family:
                    mac = direccion.address

            estado = psutil.net_if_stats().get(nombre)
            interfaces.append({
                "Interfaz": nombre,
                "IPv4": ", ".join(ipv4) or "No asignada",
                "MAC": mac or "No disponible",
                "Estado": "Activa" if estado and estado.isup else "Inactiva",
                "Velocidad": f"{estado.speed} Mbps" if estado and estado.speed else "No disponible",
            })

        conexiones = []
        try:
            for conexion in psutil.net_connections(kind="inet"):
                if conexion.status == psutil.CONN_LISTEN:
                    conexiones.append({
                        "Dirección local": f"{conexion.laddr.ip}:{conexion.laddr.port}",
                        "PID": conexion.pid or "Desconocido",
                    })
        except (psutil.AccessDenied, psutil.Error):
            conexiones.append({"Estado": "Se requieren permisos para ver puertos en escucha"})

        gateway = AuditoriaProfesional._ejecutar(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
             "Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty NextHop)"],
            "No disponible",
        )
        dns = AuditoriaProfesional._ejecutar(
            ["powershell", "-NoProfile", "-Command",
             "(Get-DnsClientServerAddress -AddressFamily IPv4 | "
             "ForEach-Object {$_.ServerAddresses} | Where-Object {$_} | Select-Object -Unique) -join ', '"],
            "No disponible",
        )
        internet = AuditoriaProfesional._probar_conectividad()

        return {
            "Equipo": socket.gethostname(),
            "Gateway": gateway,
            "DNS": dns,
            "Internet": internet,
            "Interfaces": interfaces,
            "Puertos en escucha": conexiones,
        }

    @staticmethod
    def auditoria_seguridad() -> dict:
        firewall = AuditoriaProfesional._ejecutar(
            ["netsh", "advfirewall", "show", "allprofiles"], "No disponible"
        )
        firewall_activo = "State                                 ON" in firewall or "\nState                              ON" in firewall

        defender = AuditoriaProfesional._ejecutar(
            ["powershell", "-NoProfile", "-Command",
             "try { (Get-MpComputerStatus | Select-Object AntivirusEnabled, "
             "RealTimeProtectionEnabled, AntivirusSignatureLastUpdated | ConvertTo-Json -Compress) } "
             "catch { 'No disponible' }"],
            "No disponible",
        )
        actualizaciones = AuditoriaProfesional._ejecutar(
            ["powershell", "-NoProfile", "-Command",
             "try { (Get-HotFix | Sort-Object InstalledOn -Descending | "
             "Select-Object -First 1 -ExpandProperty InstalledOn) } catch { 'No disponible' }"],
            "No disponible",
        )

        return {
            "Sistema": platform.platform(),
            "Firewall de Windows": "Activo" if firewall_activo else "Revisar estado",
            "Microsoft Defender": defender,
            "Última actualización instalada": actualizaciones,
            "Fecha de auditoría": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        }

    @staticmethod
    def _probar_conectividad() -> str:
        try:
            socket.create_connection(("www.microsoft.com", 443), timeout=3).close()
            return "Disponible"
        except OSError:
            return "Sin conexión o bloqueada"

    @staticmethod
    def _ejecutar(comando, predeterminado: str) -> str:
        try:
            resultado = subprocess.run(
                comando,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            salida = (resultado.stdout or "").strip()
            return salida or predeterminado
        except (OSError, subprocess.SubprocessError):
            return predeterminado

    @staticmethod
    def mostrar(datos: dict, titulo: str):
        print("\n" + "=" * 60)
        print(f"  {titulo}")
        print("=" * 60)
        AuditoriaProfesional._mostrar_valores(datos)

    @staticmethod
    def _mostrar_valores(datos: dict, prefijo=""):
        for clave, valor in datos.items():
            if isinstance(valor, list):
                print(f"\n  {prefijo}{clave}:")
                for indice, elemento in enumerate(valor, 1):
                    print(f"\n    #{indice}")
                    AuditoriaProfesional._mostrar_valores(elemento, "  ")
            elif isinstance(valor, dict):
                print(f"\n  {prefijo}{clave}:")
                AuditoriaProfesional._mostrar_valores(valor, "  ")
            else:
                print(f"  {prefijo}{clave:<32} {valor}")
