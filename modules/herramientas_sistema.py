"""Read-only Windows system tools with a fixed, safe command allowlist."""

import getpass
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil

from core.actions import ActionRisk
from core.permissions import registrar_accion
from core.result import DiagnosticResult
from core.severity import Severity
from modules.mantenimiento import CONFIRMATION_TOKEN, MaintenanceDiagnostics
from modules.red import NetworkDiagnostics


logger = logging.getLogger("hardware_diagnostico")
UNKNOWN = "DESCONOCIDO"
COMMAND_TIMEOUTS = {
    "sfc": 120,
    "ipconfig": 15,
    "routes": 15,
    "connections": 15,
    "disks": 30,
    "systeminfo": 30,
}

DIAGNOSTIC_COMMANDS = {
    "sfc": {
        "label": "Comprobar archivos del sistema",
        "command": ["sfc", "/verifyonly"],
    },
    "ipconfig": {
        "label": "Consultar configuración IP",
        "command": ["ipconfig", "/all"],
    },
    "routes": {
        "label": "Consultar rutas",
        "command": ["route", "print"],
    },
    "connections": {
        "label": "Consultar conexiones",
        "command": ["netstat", "-ano"],
    },
    "disks": {
        "label": "Consultar discos",
        "command": [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,"
            "OperationalStatus,Size | Format-Table -AutoSize",
        ],
    },
    "systeminfo": {
        "label": "Consultar sistema",
        "command": ["systeminfo"],
    },
}

ADMIN_TOOLS = {
    "taskmgr": ("Administrador de tareas", ["taskmgr.exe"]),
    "services": ("Servicios", ["mmc.exe", "services.msc"]),
    "devices": ("Administrador de dispositivos", ["mmc.exe", "devmgmt.msc"]),
    "events": ("Visor de eventos", ["mmc.exe", "eventvwr.msc"]),
    "performance": ("Monitor de rendimiento", ["perfmon.exe"]),
}

POWERSHELL_QUERIES = {
    "drivers": (
        "$ErrorActionPreference='Stop'; "
        "$devices=@{}; Get-CimInstance Win32_PnPEntity | ForEach-Object "
        "{if($_.PNPDeviceID){$devices[$_.PNPDeviceID]=$_}}; "
        "Get-CimInstance Win32_PnPSignedDriver | Select-Object -First 300 | "
        "ForEach-Object {$driver=$_; $device=$devices[$driver.DeviceID]; "
        "[pscustomobject]@{DeviceName=$driver.DeviceName;"
        "Manufacturer=$driver.Manufacturer;DriverVersion=$driver.DriverVersion;"
        "DriverDate=$(if($driver.DriverDate){$driver.DriverDate.ToString('yyyy-MM-dd')});"
        "InfName=$driver.InfName;IsSigned=$driver.IsSigned;"
        "State=$(if($device){$device.Status});"
        "ConfigManagerErrorCode=$(if($device){$device.ConfigManagerErrorCode})}} "
        "| ConvertTo-Json -Depth 4 -Compress"
    ),
    "devices": (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_PnPEntity | "
        "Select-Object -First 500 Name,Manufacturer,PNPClass,Status,"
        "ConfigManagerErrorCode,Present,PNPDeviceID | "
        "ConvertTo-Json -Depth 4 -Compress"
    ),
    "events": (
        "$ErrorActionPreference='SilentlyContinue'; "
        "$start=(Get-Date).AddDays(-7); "
        "$items=@(Get-WinEvent -FilterHashtable "
        "@{LogName='System';StartTime=$start} -MaxEvents 200); "
        "$items | Where-Object {$_.Level -in 1,2,3 -or "
        "$_.ProviderName -match 'disk|ntfs|driver|network|tcpip|kernel|whea'} "
        "| Select-Object -First 30 @{n='Date';e={$_.TimeCreated.ToString('o')}},"
        "LevelDisplayName,ProviderName,Id,"
        "@{n='Message';e={($_.Message -replace '\\s+',' ').Substring("
        "0,[Math]::Min(300,($_.Message -replace '\\s+',' ').Length))}} "
        "| ConvertTo-Json -Depth 3 -Compress"
    ),
}

WINDOWS_INFO_QUERY = (
    "$ErrorActionPreference='Stop'; "
    "$os=Get-CimInstance Win32_OperatingSystem; "
    "[pscustomobject]@{Edition=$os.Caption; Version=$os.Version; "
    "Build=$os.BuildNumber; Architecture=$os.OSArchitecture; "
    "InstallDate=$(if($os.InstallDate){$os.InstallDate.ToString('o')}else{$null}); "
    "LastBootUpTime=$(if($os.LastBootUpTime){$os.LastBootUpTime.ToString('o')}else{$null})} "
    "| ConvertTo-Json -Compress"
)


def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(command, timeout=30):
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "return_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "error": None,
            "duration_seconds": round(time.monotonic() - start, 3),
        }
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning(
            "Comando de herramientas del sistema falló | programa=%s | error=%s",
            command[0] if command else UNKNOWN,
            error,
            exc_info=True,
        )
        return {
            "return_code": None,
            "stdout": "",
            "stderr": "",
            "error": str(error),
            "duration_seconds": round(time.monotonic() - start, 3),
        }


def _powershell_json(script, command_runner=None):
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        return None, "PowerShell no está disponible."
    runner = command_runner or _run
    result = runner(
        [
            executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-Command", script,
        ],
        timeout=30,
    )
    if result.get("return_code") != 0 or not result.get("stdout", "").strip():
        return None, result.get("error") or result.get("stderr") or "Consulta no disponible."
    try:
        value = json.loads(result["stdout"])
    except (json.JSONDecodeError, TypeError):
        return None, "PowerShell devolvió datos con formato no válido."
    if isinstance(value, dict):
        return [value], None
    if isinstance(value, list):
        return value, None
    return [], None


@dataclass
class SystemToolReport:
    finding: DiagnosticResult
    data: Any
    source: str
    findings: List[DiagnosticResult] = field(default_factory=list)

    def to_dict(self):
        return {
            **self.finding.to_dict(),
            "data": self.data,
            "source": self.source,
            "findings": [finding.to_dict() for finding in self.findings],
        }


class SystemToolsDiagnostics:
    """Collect Windows facts, using existing maintenance and network services."""

    def __init__(
        self,
        command_runner=None,
        powershell_query=None,
        maintenance=None,
        network=None,
        launcher=None,
    ):
        self._run = command_runner or _run
        self._powershell_query = powershell_query
        self.maintenance = maintenance or MaintenanceDiagnostics()
        self.network = network or NetworkDiagnostics()
        self._launcher = launcher or subprocess.Popen

    def _query(self, name):
        if self._powershell_query:
            try:
                rows = self._powershell_query(POWERSHELL_QUERIES[name])
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                logger.warning("Consulta PowerShell %s falló: %s", name, error)
                return None, str(error)
            if rows is None:
                return None, "La consulta de Windows no está disponible."
            return _rows(rows), None
        return _powershell_json(POWERSHELL_QUERIES[name], self._run)

    @staticmethod
    def _report(
        code,
        title,
        data,
        source,
        description="Consulta informativa completada; no se modificó el equipo.",
        severity=Severity.INFORMATION,
        findings=None,
        recommendation="",
    ):
        finding = DiagnosticResult(
            code=code,
            component="HERRAMIENTAS DEL SISTEMA",
            title=title,
            description=description,
            evidence=data,
            severity=severity,
            recommendation=recommendation,
            source=source,
        )
        return SystemToolReport(
            finding=finding,
            data=data,
            source=source,
            findings=findings or [finding],
        )

    def windows_info(self):
        data = {
            "edition": UNKNOWN,
            "version": platform.release() or UNKNOWN,
            "build": UNKNOWN,
            "architecture": platform.machine() or UNKNOWN,
            "computer_name": socket.gethostname() or UNKNOWN,
            "user": getpass.getuser() or UNKNOWN,
            "install_date": UNKNOWN,
            "last_boot": UNKNOWN,
            "uptime_seconds": UNKNOWN,
        }
        query_error = None
        if self._powershell_query:
            try:
                rows = self._powershell_query(WINDOWS_INFO_QUERY)
                rows = _rows(rows)
                row = rows[0] if rows else {}
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                logger.warning("No se pudo consultar información de Windows: %s", error)
                row, query_error = {}, str(error)
        else:
            rows, query_error = _powershell_json(WINDOWS_INFO_QUERY, self._run)
            row = rows[0] if rows else {}
        if isinstance(row, dict):
            for source, target in (
                ("Edition", "edition"),
                ("Version", "version"),
                ("Build", "build"),
                ("Architecture", "architecture"),
                ("InstallDate", "install_date"),
                ("LastBootUpTime", "last_boot"),
            ):
                if row.get(source):
                    data[target] = row[source]
        try:
            boot_time = psutil.boot_time()
            data["uptime_seconds"] = max(0, int(time.time() - boot_time))
            if data["last_boot"] == UNKNOWN:
                data["last_boot"] = datetime.fromtimestamp(
                    boot_time
                ).astimezone().isoformat(timespec="seconds")
        except (OSError, ValueError, psutil.Error) as error:
            logger.info("No se pudo calcular el tiempo de actividad: %s", error)
        report = self._report(
            "SYSTEM_TOOLS_WINDOWS_INFO",
            "Información de Windows",
            data,
            "CIM Win32_OperatingSystem / platform / psutil",
        )
        if query_error:
            report.data["query_error"] = query_error
            report.finding.evidence = report.data
        return report

    def environment_variables(self, search=None):
        relevant = (
            "PATH", "TEMP", "TMP", "USERNAME", "COMPUTERNAME",
            "USERPROFILE", "SystemRoot",
        )
        if search:
            if not search.replace("_", "").isalnum():
                return self._report(
                    "SYSTEM_TOOLS_ENVIRONMENT",
                    "Variables de entorno",
                    {"error": "Nombre de variable no válido.", "variables": {}},
                    "os.environ",
                    description="No se consultó la variable porque el nombre no es válido.",
                )
            name = next(
                (key for key in os.environ if key.casefold() == search.casefold()),
                search,
            )
            values = {name: os.environ.get(name, UNKNOWN)}
        else:
            values = {name: os.environ.get(name, UNKNOWN) for name in relevant}
        return self._report(
            "SYSTEM_TOOLS_ENVIRONMENT",
            "Variables de entorno",
            {"variables": values},
            "os.environ",
        )

    def processes(self, sort_by="memory"):
        records = self.maintenance.list_processes()
        sort_by = "cpu" if str(sort_by).casefold() == "cpu" else "memory"
        key = "cpu_percent" if sort_by == "cpu" else "memory_bytes"
        records = sorted(
            records,
            key=lambda item: item.get(key) or 0,
            reverse=True,
        )
        return self._report(
            "SYSTEM_TOOLS_PROCESSES",
            "Procesos y tareas",
            {"sort_by": sort_by, "processes": records},
            "MaintenanceDiagnostics.list_processes / psutil",
        )

    def services(self):
        records = self.maintenance.services_info(all_services=True)
        return self._report(
            "SYSTEM_TOOLS_SERVICES",
            "Servicios del sistema",
            {"services": records},
            "MaintenanceDiagnostics.services_info / CIM",
        )

    def drivers(self):
        rows, error = self._query("drivers")
        data = {"drivers": rows or [], "available": error is None}
        if error:
            data["error"] = error
        return self._report(
            "SYSTEM_TOOLS_DRIVERS",
            "Controladores",
            data,
            "PowerShell CIM Win32_PnPSignedDriver",
            description=(
                "No fue posible obtener información de controladores."
                if error else "Controladores consultados; no se modificó el equipo."
            ),
        )

    def devices(self):
        rows, error = self._query("devices")
        rows = rows or []
        findings = []
        for device in rows:
            if not isinstance(device, dict):
                continue
            code = device.get("ConfigManagerErrorCode")
            status = str(device.get("Status") or "").casefold()
            configuration_error = code not in (None, 0, "0")
            failed_status = status in (
                "error", "failed", "pred fail", "non-operational",
                "nonoperational", "lost communication",
            )
            if configuration_error or failed_status:
                findings.append(
                    DiagnosticResult(
                        code="SYSTEM_TOOLS_DEVICE_PROBLEM",
                        component="DISPOSITIVOS",
                        title=device.get("Name") or "Dispositivo con estado anómalo",
                        description="Windows reporta un estado o código de configuración que requiere revisión.",
                        evidence=device,
                        severity=Severity.ALERT,
                        recommendation="Revisar el estado del dispositivo y su controlador en el Administrador de dispositivos.",
                        current_value={"status": device.get("Status"), "code": code},
                        expected_value={"status": "OK", "code": 0},
                        source="PowerShell CIM Win32_PnPEntity",
                    )
                )
        data = {"devices": rows, "available": error is None}
        if error:
            data["error"] = error
        severity = Severity.ALERT if findings else Severity.INFORMATION
        report = self._report(
            "SYSTEM_TOOLS_DEVICES",
            "Dispositivos",
            data,
            "PowerShell CIM Win32_PnPEntity",
            description=(
                "No fue posible consultar dispositivos."
                if error else "Dispositivos consultados sin modificar el equipo."
            ),
            severity=severity,
            findings=findings or None,
        )
        if not findings:
            report.findings = [report.finding]
        else:
            report.findings.insert(0, report.finding)
        return report

    def network_info(self):
        try:
            configuration = self.network.get_configuration()
            adapters = []
            for adapter in configuration.adapters:
                adapters.append(
                    {
                        "name": adapter.name or UNKNOWN,
                        "type": adapter.adapter_type or UNKNOWN,
                        "status": adapter.status or UNKNOWN,
                        "mac": adapter.mac_address or UNKNOWN,
                        "ipv4": adapter.ipv4 or [UNKNOWN],
                        "ipv6": adapter.ipv6 or [UNKNOWN],
                        "gateway": adapter.gateways or [UNKNOWN],
                        "dns": adapter.dns_servers or [UNKNOWN],
                    }
                )
            data = {
                "hostname": configuration.hostname or UNKNOWN,
                "adapters": adapters,
            }
        except (OSError, RuntimeError, psutil.Error) as error:
            logger.exception("No se pudo reutilizar el diagnóstico de red")
            data = {"error": str(error), "adapters": []}
        return self._report(
            "SYSTEM_TOOLS_NETWORK",
            "Información de red",
            data,
            "NetworkDiagnostics.get_configuration",
        )

    def recent_events(self):
        rows, error = self._query("events")
        data = {"events": rows or [], "available": error is None}
        if error:
            data["error"] = error
        return self._report(
            "SYSTEM_TOOLS_RECENT_EVENTS",
            "Eventos recientes",
            data,
            "PowerShell Get-WinEvent, registro System (últimos 7 días)",
            description=(
                "No fue posible consultar eventos recientes."
                if error else "Eventos consultados en modo de solo lectura."
            ),
        )

    def run_diagnostic_command(self, command_id):
        spec = DIAGNOSTIC_COMMANDS.get(command_id)
        if spec is None:
            return {
                "success": False,
                "error": "Comando no permitido.",
                "stdout": "",
                "stderr": "",
                "return_code": None,
                "duration_seconds": 0,
                "timestamp": _timestamp(),
                "command": [],
            }
        started = time.monotonic()
        result = self._run(
            list(spec["command"]),
            timeout=COMMAND_TIMEOUTS[command_id],
        )
        duration = result.get("duration_seconds")
        if duration is None:
            duration = round(time.monotonic() - started, 3)
        success = result.get("return_code") == 0
        finding = DiagnosticResult(
            code=f"SYSTEM_TOOLS_COMMAND_{command_id.upper()}",
            component="COMANDOS DE DIAGNÓSTICO",
            title=spec["label"],
            description=(
                "El comando terminó correctamente."
                if success
                else "El comando no terminó correctamente; revisa salida y error."
            ),
            evidence={
                "return_code": result.get("return_code"),
                "stderr": result.get("stderr", ""),
                "error": result.get("error"),
                "duration_seconds": duration,
            },
            severity=Severity.INFORMATION,
            recommendation=(
                "Algunos comandos requieren permisos elevados; no se solicitó elevación."
                if result.get("return_code") not in (0, None)
                or result.get("error")
                else ""
            ),
            source="Comando nativo de Windows",
        )
        return {
            "success": success,
            "command": list(spec["command"]),
            "return_code": result.get("return_code"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error"),
            "duration_seconds": duration,
            "timestamp": _timestamp(),
            "finding": finding.to_dict(),
        }

    def launch_admin_tool(
        self,
        tool_id,
        professional=False,
        confirm_token="",
    ):
        tool = ADMIN_TOOLS.get(tool_id)
        label = tool[0] if tool else UNKNOWN
        if tool is None:
            return {"success": False, "tool": label, "error": "Herramienta no permitida."}
        if not professional:
            return {
                "success": False,
                "tool": label,
                "error": "Disponible únicamente en Modo Profesional.",
            }
        if confirm_token != CONFIRMATION_TOKEN:
            return {
                "success": False,
                "tool": label,
                "error": "Se requiere escribir CONFIRMAR.",
            }
        if os.name != "nt":
            return {
                "success": False,
                "tool": label,
                "error": "Herramienta disponible únicamente en Windows.",
            }
        command = list(tool[1])
        try:
            self._launcher(
                command,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            result = {"success": True, "tool": label, "command": command}
            logger.info("Herramienta administrativa iniciada | herramienta=%s", label)
            registrar_accion(
                f"Abrir herramienta administrativa: {label}",
                ActionRisk.PROFESSIONAL,
                modo_profesional=True,
            )
            return result
        except (OSError, subprocess.SubprocessError) as error:
            logger.exception("No se pudo iniciar herramienta administrativa: %s", label)
            registrar_accion(
                f"Error al abrir herramienta administrativa: {label}",
                ActionRisk.PROFESSIONAL,
                modo_profesional=True,
            )
            return {"success": False, "tool": label, "error": str(error)}


def _rows(value):
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []
