"""Windows maintenance inventory and explicitly authorized actions."""

import getpass
import json
import logging
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from core.actions import ActionRisk
from core.result import DiagnosticResult
from core.severity import Severity
from core.thresholds import THRESHOLDS


logger = logging.getLogger("hardware_diagnostico")

MAINTENANCE_THRESHOLDS = {
    "temporary_review_bytes": 100 * 1024 * 1024,
    "recycle_review_bytes": 500 * 1024 * 1024,
    "startup_review_count": 8,
    "process_memory_review_percent": 25.0,
    "directory_scan_entries": 4000,
    "temporary_minimum_age_seconds": 24 * 60 * 60,
    "temporary_scan_entries": 10000,
}
CONFIRMATION_TOKEN = "CONFIRMAR"
CRITICAL_PROCESS_NAMES = {
    "csrss.exe", "dwm.exe", "fontdrvhost.exe", "lsass.exe", "services.exe",
    "smss.exe", "spoolsv.exe", "svchost.exe", "system", "system idle process",
    "wininit.exe", "winlogon.exe", "winmgmt.exe", "registry",
}
PROTECTED_SERVICES = {
    "bfe", "dcomlaunch", "eventlog", "mpssvc", "plugplay", "rpcss",
    "securityhealthservice", "windefend", "wininit", "winmgmt", "wscsvc",
}
MANAGED_SERVICES = {
    "bits", "spooler", "wsearch", "wuauserv", "sysmain",
    "windefend", "mpssvc", "wscsvc", "securityhealthservice",
}
POWERSHELL_TIMEOUT_SECONDS = 18


def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(command, timeout=POWERSHELL_TIMEOUT_SECONDS):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "return_code": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "error": None,
        }
    except subprocess.TimeoutExpired as error:
        logger.warning("Comando de mantenimiento agotó tiempo: %s", command[0])
        return {
            "return_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Tiempo de espera agotado ({error.timeout} s).",
        }
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning(
            "Comando de mantenimiento falló | comando=%s | error=%s",
            command[0] if command else "desconocido",
            error,
            exc_info=True,
        )
        return {
            "return_code": None,
            "stdout": "",
            "stderr": "",
            "error": str(error),
        }


def _powershell_executable():
    return shutil.which("powershell.exe") or shutil.which("powershell")


def _powershell_json(script, timeout=POWERSHELL_TIMEOUT_SECONDS):
    executable = _powershell_executable()
    if not executable:
        return None
    result = _run(
        [
            executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-Command", script,
        ],
        timeout=timeout,
    )
    if result["return_code"] != 0 or not result["stdout"].strip():
        logger.info(
            "Consulta PowerShell de mantenimiento no disponible | error=%s",
            result["error"] or result["stderr"][-500:],
        )
        return None
    try:
        value = json.loads(result["stdout"])
    except json.JSONDecodeError:
        logger.warning("PowerShell devolvió JSON inválido para mantenimiento")
        return None
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


@dataclass
class MaintenanceCheck:
    name: str
    status: Optional[bool]
    severity: Severity
    evidence: Any = field(default_factory=dict)
    description: str = ""


@dataclass
class MaintenanceAuditResult:
    timestamp: str
    computer: str
    memory: Dict[str, Any]
    storage: List[Dict[str, Any]]
    processes: List[Dict[str, Any]]
    temporary_files: Dict[str, Any]
    recycle_bin: Dict[str, Any]
    startup_items: List[Dict[str, Any]]
    services: List[Dict[str, Any]]
    checks: List[MaintenanceCheck]
    recommendations: List[DiagnosticResult]
    severity: Severity

    @property
    def findings(self):
        return self.recommendations

    def to_dict(self):
        temporary_summary = {
            key: value for key, value in self.temporary_files.items()
            if key not in ("files", "errors")
        }
        temporary_summary["error_count"] = len(
            self.temporary_files.get("errors", [])
        )
        return {
            "timestamp": self.timestamp,
            "computer": self.computer,
            "memory": self.memory,
            "storage": self.storage,
            "processes": self.processes,
            "temporary_files": temporary_summary,
            "recycle_bin": self.recycle_bin,
            "startup_items": self.startup_items,
            "services": self.services,
            "checks": [
                {
                    **asdict(check),
                    "severity": check.severity.label,
                }
                for check in self.checks
            ],
            "recommendations": [
                _finding_dict(finding) for finding in self.recommendations
            ],
            "severity": self.severity.label,
        }


@dataclass
class MaintenanceActionResult:
    action: str
    success: bool
    computer: str
    user: str
    timestamp: str
    target: Any = None
    result: str = ""
    error: Optional[str] = None
    risk: str = ActionRisk.CONFIRMATION.value
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class MaintenanceDiagnostics:
    """Read maintenance state and perform separately confirmed operations."""

    def __init__(self, command_runner=None, powershell_query=None):
        self._run = command_runner or _run
        self._powershell_query = powershell_query or _powershell_json

    def list_processes(self):
        processes = []
        sampled = []
        total_memory = psutil.virtual_memory().total
        for process in psutil.process_iter(
            attrs=("pid", "name", "username", "status", "memory_info")
        ):
            try:
                info = process.info
                memory = info.get("memory_info")
                process.cpu_percent(interval=None)
                sampled.append((process, info, memory))
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (OSError, RuntimeError):
                logger.warning("No se pudo leer un proceso", exc_info=True)
        if sampled:
            time.sleep(0.1)
        for process, info, memory in sampled:
            try:
                cpu = process.cpu_percent(interval=None)
                try:
                    path = process.exe()
                except (
                    psutil.AccessDenied,
                    psutil.NoSuchProcess,
                    psutil.ZombieProcess,
                    OSError,
                ):
                    path = None
                processes.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name") or "Desconocido",
                        "cpu_percent": round(cpu, 1) if cpu is not None else None,
                        "memory_bytes": memory.rss if memory else None,
                        "memory_mb": round(memory.rss / 1024 ** 2, 1)
                        if memory else None,
                        "memory_percent": round(
                            memory.rss * 100 / total_memory, 1
                        ) if memory and total_memory else None,
                        "user": info.get("username"),
                        "path": path,
                        "status": info.get("status") or "Desconocido",
                    }
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (OSError, RuntimeError):
                logger.warning("No se pudo muestrear CPU de un proceso", exc_info=True)
        processes.sort(
            key=lambda item: item["memory_bytes"] or 0,
            reverse=True,
        )
        return processes

    def memory_info(self):
        memory = psutil.virtual_memory()
        return {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "used_bytes": memory.used,
            "usage_percent": memory.percent,
            "total_gb": round(memory.total / 1024 ** 3, 2),
            "available_gb": round(memory.available / 1024 ** 3, 2),
            "used_gb": round(memory.used / 1024 ** 3, 2),
            "top_processes": self.list_processes()[:10],
        }

    def storage_info(self, scan_directories=True):
        volumes = []
        seen = set()
        try:
            partitions = psutil.disk_partitions(all=False)
        except (OSError, psutil.Error):
            logger.exception("No se pudieron enumerar unidades")
            partitions = []
        for partition in partitions:
            mount = partition.mountpoint
            if mount in seen:
                continue
            seen.add(mount)
            try:
                usage = psutil.disk_usage(mount)
            except (OSError, PermissionError, psutil.Error):
                logger.info("No se pudo consultar espacio de %s", mount)
                continue
            volumes.append(
                {
                    "mountpoint": mount,
                    "filesystem": partition.fstype or None,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "total_gb": round(usage.total / 1024 ** 3, 2),
                    "used_gb": round(usage.used / 1024 ** 3, 2),
                    "free_gb": round(usage.free / 1024 ** 3, 2),
                    "used_percent": usage.percent,
                    "largest_directories": [],
                }
            )
        if scan_directories:
            for volume in volumes:
                volume["largest_directories"] = _largest_user_directories(
                    volume["mountpoint"],
                    MAINTENANCE_THRESHOLDS["directory_scan_entries"],
                )
        return volumes

    def temporary_inventory(self):
        locations = _temporary_locations()
        files = []
        errors = []
        truncated = False
        for location in locations:
            if not location.exists() or not location.is_dir():
                continue
            for path in _walk_files(location):
                if len(files) >= MAINTENANCE_THRESHOLDS["temporary_scan_entries"]:
                    truncated = True
                    break
                try:
                    file_stat = path.stat(follow_symlinks=False)
                    if not path.is_symlink():
                        age_seconds = max(0, time.time() - file_stat.st_mtime)
                        files.append(
                            {
                                "path": str(path),
                                "size_bytes": file_stat.st_size,
                                "modified_timestamp": file_stat.st_mtime,
                                "eligible": age_seconds >= MAINTENANCE_THRESHOLDS[
                                    "temporary_minimum_age_seconds"
                                ],
                            }
                        )
                except OSError as error:
                    errors.append({"path": str(path), "error": str(error)})
            if truncated:
                break
        total_size = sum(item["size_bytes"] for item in files)
        eligible_size = sum(
            item["size_bytes"] for item in files if item["eligible"]
        )
        return {
            "locations": [str(location) for location in locations],
            "file_count": len(files),
            "size_bytes": total_size,
            "size_mb": round(total_size / 1024 ** 2, 2),
            "eligible_file_count": sum(item["eligible"] for item in files),
            "eligible_size_bytes": eligible_size,
            "eligible_size_mb": round(eligible_size / 1024 ** 2, 2),
            "truncated": truncated,
            "files": files,
            "errors": errors,
        }

    def recycle_bin_inventory(self):
        script = (
            "$shell=New-Object -ComObject Shell.Application; "
            "$folder=$shell.Namespace(10); "
            "if ($null -eq $folder) { throw 'Papelera no disponible' }; "
            "$items=@($folder.Items()); "
            "$size=0; foreach($item in $items){$size+=[int64]$item.Size}; "
            "[pscustomobject]@{Count=$items.Count; SizeBytes=$size} "
            "| ConvertTo-Json -Compress"
        )
        records = self._powershell_query(script, timeout=10)
        if not records:
            return {
                "available": False,
                "count": None,
                "size_bytes": None,
                "size_mb": None,
                "error": "Papelera no disponible",
            }
        count = _int(_get(records[0], "Count"))
        size = _int(_get(records[0], "SizeBytes"))
        return {
            "available": count is not None and size is not None,
            "count": count,
            "size_bytes": size,
            "size_mb": round(size / 1024 ** 2, 2) if size is not None else None,
            "error": None,
        }

    def startup_items(self, include_disabled=True):
        items = []
        if os.name == "nt":
            items.extend(_registry_startup_items(include_disabled))
        for folder in _startup_folders():
            try:
                entries = list(folder.iterdir())
            except OSError:
                continue
            for path in entries:
                disabled = path.name.endswith(".hd-disabled")
                if disabled and not include_disabled:
                    continue
                if not path.is_file():
                    continue
                startup_name = path.name.removesuffix(".hd-disabled")
                if Path(startup_name).suffix.casefold() not in {
                    ".bat", ".cmd", ".exe", ".lnk", ".url",
                }:
                    continue
                items.append(
                    {
                        "id": f"folder:{path}",
                        "name": startup_name,
                        "enabled": not disabled,
                        "origin": str(path.parent),
                        "command": str(path),
                        "kind": "startup_folder",
                        "scope": _startup_folder_scope(path),
                        "data_type": None,
                    }
                )
        return items

    def services_info(self, all_services=False):
        if all_services:
            script = (
                "$services=Get-CimInstance Win32_Service | ForEach-Object {"
                "[pscustomobject]@{Name=$_.Name; DisplayName=$_.DisplayName;"
                "State=$_.State; StartMode=$_.StartMode; PathName=$_.PathName;"
                "Description=$_.Description}}; "
                "@($services) | ConvertTo-Json -Depth 4 -Compress"
            )
        else:
            script = (
                "$names=@('BITS','Spooler','WSearch','wuauserv','SysMain',"
                "'WinDefend','MpsSvc','wscsvc','SecurityHealthService','BFE'); "
                "$services=Get-CimInstance Win32_Service | "
                "Where-Object {$names -contains $_.Name} | ForEach-Object {"
                "[pscustomobject]@{Name=$_.Name; DisplayName=$_.DisplayName;"
                "State=$_.State; StartMode=$_.StartMode; PathName=$_.PathName;"
                "Description=$_.Description}}; "
                "@($services) | ConvertTo-Json -Depth 4 -Compress"
            )
        records = self._powershell_query(script)
        return records or []

    def recommended_maintenance(self, professional=False):
        memory, memory_error = _safe_inventory(
            "memoria",
            self.memory_info,
            {
                "total_gb": None, "available_gb": None, "used_gb": None,
                "usage_percent": None, "top_processes": [],
            },
        )
        storage, storage_error = _safe_inventory(
            "almacenamiento",
            lambda: self.storage_info(scan_directories=professional),
            [],
        )
        temporary, temporary_error = _safe_inventory(
            "temporales",
            self.temporary_inventory,
            {
                "locations": [], "file_count": 0, "size_bytes": 0,
                "size_mb": 0, "eligible_file_count": 0,
                "eligible_size_bytes": 0, "eligible_size_mb": 0,
                "truncated": False, "files": [], "errors": [],
            },
        )
        recycle, recycle_error = _safe_inventory(
            "papelera",
            self.recycle_bin_inventory,
            {
                "available": False, "count": None, "size_bytes": None,
                "size_mb": None, "error": "No disponible",
            },
        )
        startup, startup_error = _safe_inventory(
            "programas de inicio",
            lambda: self.startup_items(include_disabled=False),
            [],
        )
        services, services_error = _safe_inventory(
            "servicios", self.services_info, []
        )
        checks = []
        findings = []

        usage_percent = _float(memory.get("usage_percent"))
        if usage_percent is None:
            _unavailable_finding(
                findings, checks, "RAM",
                memory_error or "No se pudo consultar el uso de memoria.",
            )
        elif usage_percent >= THRESHOLDS.ram_elevated_percent:
            top_processes = memory["top_processes"][:5]
            findings.append(_finding(
                "MAINTENANCE_RAM_HIGH",
                "MEMORIA",
                "Uso elevado de memoria RAM",
                Severity.ALERT,
                f"Uso de memoria actual: {usage_percent:.1f}%.",
                {"memory": memory, "top_processes": top_processes},
                usage_percent,
                f"< {THRESHOLDS.ram_elevated_percent:g}%",
                "Revisar los procesos con mayor consumo y cerrar únicamente los que reconozcas.",
            ))
            checks.append(MaintenanceCheck(
                "Memoria", False, Severity.ALERT, memory,
                "Uso elevado; revisar procesos activos.",
            ))
        else:
            checks.append(MaintenanceCheck(
                "Memoria", True, Severity.NORMAL,
                {"usage_percent": usage_percent},
                "Uso de memoria dentro de umbrales de diagnóstico.",
            ))
        total_bytes = memory.get("total_bytes")
        if total_bytes:
            high_memory_processes = [
                process for process in memory["top_processes"]
                if (
                    _float(process.get("memory_percent")) is not None
                    and process["memory_percent"]
                    >= MAINTENANCE_THRESHOLDS["process_memory_review_percent"]
                )
            ]
            for process in high_memory_processes:
                findings.append(_finding(
                    "MAINTENANCE_PROCESS_MEMORY_HIGH",
                    "PROCESOS",
                    f"{process['name']} consume una parte relevante de RAM",
                    Severity.INFORMATION,
                    f"El proceso reporta {process['memory_percent']:.1f}% "
                    "de la RAM física.",
                    process,
                    process["memory_percent"],
                    f"< {MAINTENANCE_THRESHOLDS['process_memory_review_percent']:g}%",
                    "Revisar el uso de esta aplicación; no se cerró el proceso.",
                ))

        for volume in storage:
            free_percent = 100 - volume["used_percent"]
            if (
                free_percent <= THRESHOLDS.disk_free_alert_percent
                or volume["free_gb"] <= THRESHOLDS.disk_free_alert_gb
            ):
                severity = (
                    Severity.CRITICAL
                    if free_percent <= THRESHOLDS.disk_free_critical_percent
                    or volume["free_gb"] <= THRESHOLDS.disk_free_critical_gb
                    else Severity.ALERT
                )
                findings.append(_finding(
                    "MAINTENANCE_DISK_LOW_SPACE",
                    "ALMACENAMIENTO",
                    f"Espacio libre bajo en {volume['mountpoint']}",
                    severity,
                    f"{volume['used_percent']:.1f}% utilizado; "
                    f"{volume['free_gb']:.2f} GB disponibles.",
                    volume,
                    volume["free_gb"],
                    f"> {THRESHOLDS.disk_free_alert_gb:g} GB libres",
                    "Revisar archivos grandes y temporales; no se eliminó ningún archivo.",
                ))
            checks.append(MaintenanceCheck(
                f"Almacenamiento {volume['mountpoint']}",
                free_percent > THRESHOLDS.disk_free_alert_percent
                and volume["free_gb"] > THRESHOLDS.disk_free_alert_gb,
                Severity.NORMAL if (
                    free_percent > THRESHOLDS.disk_free_alert_percent
                    and volume["free_gb"] > THRESHOLDS.disk_free_alert_gb
                ) else Severity.ALERT,
                volume,
                "Espacio disponible adecuado."
                if free_percent > THRESHOLDS.disk_free_alert_percent
                and volume["free_gb"] > THRESHOLDS.disk_free_alert_gb
                else "Revisar espacio disponible.",
            ))

        if temporary["size_bytes"] >= MAINTENANCE_THRESHOLDS["temporary_review_bytes"]:
            checks.append(MaintenanceCheck(
                "Archivos temporales", False, Severity.INFORMATION,
                {
                    "size_bytes": temporary["size_bytes"],
                    "file_count": temporary["file_count"],
                },
                "Revisar temporales; su eliminación requiere confirmación.",
            ))
            findings.append(_finding(
                "MAINTENANCE_TEMP_FILES",
                "TEMPORALES",
                "Hay archivos temporales para revisar",
                Severity.INFORMATION,
                f"{temporary['size_mb']:.2f} MB en {temporary['file_count']} archivos.",
                {
                    key: value for key, value in temporary.items()
                    if key not in ("files", "errors")
                },
                temporary["size_mb"],
                f"< {MAINTENANCE_THRESHOLDS['temporary_review_bytes'] / 1024 ** 2:g} MB",
                "Revisar los temporales y confirmar antes de eliminarlos.",
            ))
        elif not temporary_error:
            checks.append(MaintenanceCheck(
                "Archivos temporales", True, Severity.NORMAL,
                {"size_mb": temporary["size_mb"]},
                "Ocupación temporal dentro del umbral de revisión.",
            ))
        if recycle.get("available") and (
            recycle["size_bytes"] >= MAINTENANCE_THRESHOLDS["recycle_review_bytes"]
        ):
            checks.append(MaintenanceCheck(
                "Papelera", False, Severity.INFORMATION, recycle,
                "La papelera supera el umbral de revisión.",
            ))
            findings.append(_finding(
                "MAINTENANCE_RECYCLE_BIN_LARGE",
                "PAPELERA",
                "La papelera ocupa espacio",
                Severity.INFORMATION,
                f"{recycle['size_mb']:.2f} MB en {recycle['count']} elementos.",
                recycle,
                recycle["size_mb"],
                f"< {MAINTENANCE_THRESHOLDS['recycle_review_bytes'] / 1024 ** 2:g} MB",
                "Revisar su contenido y vaciarla solo si confirmas que no necesitas restaurar archivos.",
            ))
        elif recycle.get("available"):
            checks.append(MaintenanceCheck(
                "Papelera", True, Severity.NORMAL, recycle,
                "Papelera con poco espacio ocupado.",
            ))
        if len(startup) > MAINTENANCE_THRESHOLDS["startup_review_count"]:
            checks.append(MaintenanceCheck(
                "Programas de inicio", False, Severity.INFORMATION,
                {"enabled_count": len(startup)},
                "Revisar la cantidad de programas de inicio.",
            ))
            findings.append(_finding(
                "MAINTENANCE_STARTUP_ITEMS",
                "INICIO",
                "Varios programas se ejecutan al iniciar Windows",
                Severity.INFORMATION,
                f"Se detectaron {len(startup)} entradas habilitadas de inicio.",
                {"count": len(startup), "items": startup},
                len(startup),
                f"<= {MAINTENANCE_THRESHOLDS['startup_review_count']}",
                "Revisar los programas de inicio y deshabilitar solo elementos reconocidos.",
            ))
        elif not startup_error:
            checks.append(MaintenanceCheck(
                "Programas de inicio", True, Severity.NORMAL,
                {"enabled_count": len(startup)},
                "Cantidad de elementos de inicio dentro del umbral de revisión.",
            ))
        if services:
            checks.append(MaintenanceCheck(
                "Servicios", True, Severity.INFORMATION,
                {"count": len(services)},
                "Servicios relevantes consultados; no se modificó ninguno.",
            ))
        elif not services_error:
            checks.append(MaintenanceCheck(
                "Servicios", None, Severity.INFORMATION,
                {"count": 0},
                "Servicios relevantes no disponibles.",
            ))
        if not recycle.get("available"):
            _unavailable_finding(
                findings, checks, "Papelera",
                recycle.get("error") or "No se pudo consultar la papelera.",
            )
        if storage_error:
            _unavailable_finding(
                findings, checks, "Almacenamiento", storage_error
            )
        elif not storage:
            _unavailable_finding(
                findings, checks, "Almacenamiento",
                "No fue posible consultar unidades de almacenamiento.",
            )
        if temporary_error:
            _unavailable_finding(
                findings, checks, "Archivos temporales", temporary_error
            )
        elif temporary.get("errors"):
            _unavailable_finding(
                findings, checks, "Archivos temporales",
                f"No se pudieron consultar {len(temporary['errors'])} rutas.",
            )
        if recycle_error:
            _unavailable_finding(
                findings, checks, "Papelera", recycle_error
            )
        if startup_error:
            _unavailable_finding(
                findings, checks, "Programas de inicio", startup_error
            )
        if services_error:
            _unavailable_finding(
                findings, checks, "Servicios", services_error
            )
        if not findings:
            findings.append(_finding(
                "MAINTENANCE_NO_ACTION_NEEDED",
                "MANTENIMIENTO",
                "No se detectaron necesidades de mantenimiento prioritarias",
                Severity.NORMAL,
                "Los indicadores medidos no superan los umbrales de revisión.",
                {
                    "memory_usage_percent": usage_percent,
                    "storage_count": len(storage),
                    "temporary_mb": temporary["size_mb"],
                    "startup_count": len(startup),
                },
                True,
                True,
            ))
        actionable = [
            item.severity for item in findings
            if item.severity >= Severity.ALERT
        ]
        severity = max(actionable) if actionable else (
            Severity.NORMAL if any(
                item.severity == Severity.NORMAL for item in findings
            ) else Severity.INFORMATION
        )
        return MaintenanceAuditResult(
            timestamp=_timestamp(),
            computer=socket.gethostname(),
            memory=memory,
            storage=storage,
            processes=memory["top_processes"],
            temporary_files=temporary,
            recycle_bin=recycle,
            startup_items=startup,
            services=services,
            checks=checks,
            recommendations=findings,
            severity=severity,
        )

    def terminate_process(self, pid, confirm_token):
        if confirm_token != CONFIRMATION_TOKEN:
            return self._action(
                "finalizar proceso", False, pid, "Cancelado",
                "Se requiere escribir CONFIRMAR.",
            )
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return self._action(
                "finalizar proceso", False, pid, "Fallido",
                "PID no válido.",
            )
        if pid <= 0 or pid in (4, os.getpid()):
            return self._action(
                "finalizar proceso", False, pid, "Bloqueado",
                "No se permite finalizar este PID desde la herramienta.",
            )
        try:
            process = psutil.Process(pid)
            name = process.name()
            if name.casefold() in CRITICAL_PROCESS_NAMES:
                return self._action(
                    "finalizar proceso", False, pid, "Bloqueado",
                    "Proceso crítico protegido por la política de seguridad.",
                    {"name": name},
                )
            process.terminate()
            process.wait(timeout=5)
        except psutil.AccessDenied as error:
            return self._action(
                "finalizar proceso", False, pid, "Permiso denegado",
                str(error) or "Se requieren permisos adicionales.",
            )
        except psutil.NoSuchProcess:
            return self._action(
                "finalizar proceso", False, pid, "No encontrado",
                "El proceso ya no existe.",
            )
        except psutil.TimeoutExpired:
            return self._action(
                "finalizar proceso", False, pid, "Tiempo agotado",
                "El proceso no terminó dentro del tiempo de espera.",
            )
        except (OSError, psutil.Error) as error:
            return self._action(
                "finalizar proceso", False, pid, "Fallido", str(error),
            )
        return self._action(
            "finalizar proceso", True, pid, "Finalizado",
            details={"name": name},
        )

    def release_memory(self):
        memory = self.memory_info()
        return {
            "memory": {key: value for key, value in memory.items() if key != "top_processes"},
            "top_processes": memory["top_processes"],
            "message": "No se modifica ni aumenta la RAM; revise procesos y decida cuáles cerrar.",
        }

    def delete_temporary_files(self, confirm_token):
        if confirm_token != CONFIRMATION_TOKEN:
            return self._action(
                "eliminar archivos temporales", False, None, "Cancelado",
                "Se requiere escribir CONFIRMAR.",
            )
        inventory = self.temporary_inventory()
        allowed_roots = [path.resolve() for path in _temporary_locations()]
        deleted = 0
        deleted_bytes = 0
        errors = []
        for entry in inventory["files"]:
            candidate = Path(entry["path"])
            try:
                if not entry["eligible"]:
                    continue
                resolved = candidate.resolve(strict=True)
                if not _within_roots(resolved, allowed_roots):
                    errors.append({"path": entry["path"], "error": "Ruta fuera de temporales autorizados."})
                    continue
                file_stat = candidate.lstat()
                if not _is_regular_file(file_stat) or _is_reparse_point(file_stat):
                    errors.append({
                        "path": entry["path"],
                        "error": "El elemento no es un archivo regular permitido.",
                    })
                    continue
                if (
                    time.time() - file_stat.st_mtime
                    < MAINTENANCE_THRESHOLDS["temporary_minimum_age_seconds"]
                ):
                    errors.append({
                        "path": entry["path"],
                        "error": "El archivo se modificó recientemente; se omitió.",
                    })
                    continue
                os.remove(candidate)
                deleted += 1
                deleted_bytes += entry["size_bytes"]
            except (OSError, PermissionError) as error:
                errors.append({"path": entry["path"], "error": str(error)})
        if inventory["truncated"]:
            errors.append({
                "path": "inventario",
                "error": "El análisis alcanzó el límite de entradas.",
            })
        errors.extend(inventory["errors"])
        complete = (
            not errors
            and deleted == inventory["eligible_file_count"]
        )
        return self._action(
            "eliminar archivos temporales",
            complete,
            {"locations": inventory["locations"]},
            "Completado" if complete else "Parcial",
            None if complete else f"No se pudieron eliminar {len(errors)} elementos.",
            {
                "deleted_count": deleted,
                "deleted_bytes": deleted_bytes,
                "errors": errors[:100],
                "requested_bytes": inventory["eligible_size_bytes"],
                "requested_count": inventory["eligible_file_count"],
            },
        )

    def empty_recycle_bin(self, confirm_token):
        if confirm_token != CONFIRMATION_TOKEN:
            return self._action(
                "vaciar papelera", False, None, "Cancelado",
                "Se requiere escribir CONFIRMAR.",
            )
        if os.name != "nt":
            return self._action(
                "vaciar papelera", False, None, "No disponible",
                "Esta operación solo está disponible en Windows.",
            )
        script = (
            "Clear-RecycleBin -Force -ErrorAction Stop; "
            "[pscustomobject]@{Success=$true} | ConvertTo-Json -Compress"
        )
        executable = _powershell_executable()
        if not executable:
            return self._action(
                "vaciar papelera", False, None, "No disponible",
                "PowerShell no está disponible.",
            )
        result = self._run(
            [
                executable, "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            timeout=45,
        )
        success = result["return_code"] == 0
        return self._action(
            "vaciar papelera", success, None,
            "Completado" if success else "Fallido",
            result["error"] or (result["stderr"] or "").strip() or None,
            {"command": "Clear-RecycleBin -Force"},
        )

    def disable_startup_item(self, item_id, confirm_token, professional=False):
        if confirm_token != CONFIRMATION_TOKEN:
            return self._action(
                "deshabilitar programa de inicio", False, item_id, "Cancelado",
                "Se requiere escribir CONFIRMAR.",
            )
        item = next(
            (
                current for current in self.startup_items(include_disabled=False)
                if current["id"] == item_id
            ),
            None,
        )
        if item is None:
            return self._action(
                "deshabilitar programa de inicio", False, item_id,
                "No encontrado", "La entrada ya no está disponible.",
            )
        if item["scope"] == "machine" and not professional:
            return self._action(
                "deshabilitar programa de inicio", False, item_id,
                "Bloqueado",
                "Deshabilitar elementos de inicio de equipo requiere Modo Profesional.",
                risk=ActionRisk.PROFESSIONAL,
            )
        if item["scope"] not in ("user", "machine"):
            return self._action(
                "deshabilitar programa de inicio", False, item_id,
                "Bloqueado", "No se pudo determinar el alcance de esta entrada.",
            )
        try:
            if item["kind"] == "registry":
                _disable_registry_startup(item)
            else:
                path = Path(item["command"])
                if path.suffix.casefold() == ".hd-disabled":
                    raise ValueError("La entrada ya está deshabilitada.")
                destination = path.with_name(path.name + ".hd-disabled")
                if destination.exists():
                    raise FileExistsError("Ya existe una copia deshabilitada.")
                os.replace(path, destination)
        except (OSError, PermissionError, ValueError) as error:
            return self._action(
                "deshabilitar programa de inicio", False, item_id,
                "Fallido", str(error),
            )
        return self._action(
            "deshabilitar programa de inicio", True, item_id, "Deshabilitado",
            details={"name": item["name"], "origin": item["origin"]},
            risk=(
                ActionRisk.PROFESSIONAL
                if item["scope"] == "machine"
                else ActionRisk.CONFIRMATION
            ),
        )

    def restore_startup_item(self, item_id, confirm_token, professional=False):
        if confirm_token != CONFIRMATION_TOKEN:
            return self._action(
                "restaurar programa de inicio", False, item_id, "Cancelado",
                "Se requiere escribir CONFIRMAR.",
            )
        item = next(
            (
                current for current in self.startup_items(include_disabled=True)
                if current["id"] == item_id and not current["enabled"]
            ),
            None,
        )
        if item is None:
            return self._action(
                "restaurar programa de inicio", False, item_id,
                "No encontrado", "No existe una entrada deshabilitada con ese ID.",
            )
        if item["scope"] == "machine" and not professional:
            return self._action(
                "restaurar programa de inicio", False, item_id,
                "Bloqueado",
                "Restaurar elementos de inicio de equipo requiere Modo Profesional.",
                risk=ActionRisk.PROFESSIONAL,
            )
        try:
            if item["kind"] == "registry":
                _restore_registry_startup(item)
            else:
                path = Path(item["command"])
                destination = path.with_name(
                    path.name.removesuffix(".hd-disabled")
                )
                if destination.exists():
                    raise FileExistsError("Ya existe una entrada con el nombre original.")
                os.replace(path, destination)
        except (OSError, PermissionError, ValueError) as error:
            return self._action(
                "restaurar programa de inicio", False, item_id, "Fallido", str(error),
            )
        return self._action(
            "restaurar programa de inicio", True, item_id, "Restaurado",
            details={"name": item["name"]},
            risk=(
                ActionRisk.PROFESSIONAL
                if item["scope"] == "machine"
                else ActionRisk.CONFIRMATION
            ),
        )

    def change_service(self, name, operation, confirm_token, professional=False):
        service = str(name or "").strip()
        operation = str(operation or "").casefold()
        if operation not in ("start", "stop", "restart"):
            return self._action(
                "modificar servicio", False, service, "Bloqueado",
                "Operación de servicio no válida.",
            )
        if confirm_token != CONFIRMATION_TOKEN:
            return self._action(
                operation, False, service, "Cancelado",
                "Se requiere escribir CONFIRMAR.",
            )
        if not professional:
            return self._action(
                operation, False, service, "Bloqueado",
                "Modificar servicios solo está disponible en Modo Profesional.",
                risk=(
                    ActionRisk.CONFIRMATION
                    if operation == "restart"
                    else ActionRisk.PROFESSIONAL
                ),
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", service):
            return self._action(
                operation, False, service, "Bloqueado",
                "Nombre de servicio no válido.",
            )
        if service.casefold() in PROTECTED_SERVICES:
            return self._action(
                operation, False, service, "Bloqueado",
                "Servicio crítico protegido; no se permite modificarlo.",
            )
        if service.casefold() not in MANAGED_SERVICES:
            return self._action(
                operation, False, service, "Bloqueado",
                "Este módulo solo permite servicios incluidos en la lista administrada.",
            )
        if os.name != "nt":
            return self._action(
                operation, False, service, "No disponible",
                "La administración de servicios solo está disponible en Windows.",
            )
        executable = shutil.which("sc.exe") or shutil.which("sc")
        if not executable:
            return self._action(
                operation, False, service, "No disponible",
                "sc.exe no está disponible.",
            )
        commands = (
            [[executable, "stop", service], [executable, "start", service]]
            if operation == "restart"
            else [[executable, operation, service]]
        )
        outputs = []
        for command in commands:
            result = self._run(command, timeout=25)
            outputs.append(result)
            if result["return_code"] != 0:
                break
            if operation == "restart" and command[1] == "stop":
                time.sleep(1)
        success = (
            len(outputs) == len(commands)
            and all(output["return_code"] == 0 for output in outputs)
        )
        error = next(
            (
                output["error"] or output["stderr"] or output["stdout"]
                for output in outputs if output["return_code"] != 0
            ),
            None,
        )
        return self._action(
            operation, success, service,
            "Completado" if success else "Fallido",
            error,
            {
                "commands": [" ".join(command[1:]) for command in commands],
                "outputs": outputs,
            },
            risk=(
                ActionRisk.CONFIRMATION
                if operation == "restart"
                else ActionRisk.PROFESSIONAL
            ),
        )

    def _action(
        self, action, success, target, result, error=None, details=None,
        risk=ActionRisk.CONFIRMATION,
    ):
        record = MaintenanceActionResult(
            action=action,
            success=bool(success),
            computer=socket.gethostname(),
            user=_current_user(),
            timestamp=_timestamp(),
            target=target,
            result=result,
            error=error,
            risk=risk.value,
            details=details or {},
        )
        logger.info(
            "Mantenimiento | timestamp=%s | equipo=%s | usuario=%s | acción=%s "
            "| riesgo=%s | resultado=%s | error=%s",
            record.timestamp,
            record.computer,
            record.user,
            record.action,
            record.risk,
            record.result,
            record.error,
        )
        if not success:
            logger.warning(
                "Acción de mantenimiento no completada | acción=%s | destino=%s | error=%s",
                action,
                target,
                error,
            )
        return record


def _finding(code, component, title, severity, description, evidence,
             current_value=None, expected_value=None, recommendation=""):
    return DiagnosticResult(
        code=code,
        component=component,
        title=title,
        description=description,
        evidence=evidence,
        severity=severity,
        recommendation=recommendation,
        current_value=current_value,
        expected_value=expected_value,
        confidence="MEDIA" if severity >= Severity.ALERT else "ALTA",
        source="psutil / Windows",
        rule_id=code,
    )


def _unavailable_finding(findings, checks, name, error):
    evidence = {"error": str(error)}
    checks.append(
        MaintenanceCheck(
            name,
            None,
            Severity.INFORMATION,
            evidence,
            "No disponible",
        )
    )
    findings.append(
        _finding(
            f"MAINTENANCE_{name.upper().replace(' ', '_')}_UNAVAILABLE",
            name.upper(),
            f"{name}: información no disponible",
            Severity.INFORMATION,
            str(error),
            evidence,
        )
    )


def _safe_inventory(name, operation, fallback):
    try:
        return operation(), None
    except Exception as error:
        logger.exception("Falló la consulta de mantenimiento: %s", name)
        return fallback, str(error)


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finding_dict(finding):
    result = finding.to_dict()
    if finding.code == "MAINTENANCE_TEMP_FILES":
        evidence = finding.evidence
        result["evidence"] = {
            key: value for key, value in evidence.items()
            if key not in ("files", "errors")
        }
        result["evidence"]["error_count"] = len(evidence.get("errors", []))
    return result


def _temporary_locations():
    locations = []
    user_temp = Path(tempfile.gettempdir())
    if user_temp.exists():
        try:
            user_temp_resolved = user_temp.resolve()
            profile = Path.home().resolve()
            if user_temp_resolved != profile:
                user_temp_resolved.relative_to(profile)
                locations.append(user_temp)
        except (OSError, ValueError):
            logger.warning(
                "Se omitió una ruta temporal fuera del perfil del usuario: %s",
                user_temp,
            )
    windows_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    windows_temp = windows_root / "Temp"
    if windows_temp.exists() and windows_temp.resolve() not in {
        location.resolve() for location in locations
    }:
        locations.append(windows_temp)
    return locations


def _walk_files(root):
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories
            if not _is_reparse_path(Path(current) / name)
        ]
        for filename in filenames:
            path = Path(current) / filename
            if not _is_reparse_path(path):
                yield path


def _is_reparse_path(path):
    try:
        return _is_reparse_point(path.lstat())
    except OSError:
        return True


def _is_reparse_point(stat_result):
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(
        attributes & getattr(stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _is_regular_file(stat_result):
    return stat.S_ISREG(stat_result.st_mode)


def _within_roots(path, roots):
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _startup_folders():
    folders = []
    appdata = os.environ.get("APPDATA")
    program_data = os.environ.get("PROGRAMDATA")
    if appdata:
        folders.append(
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        )
    if program_data:
        folders.append(
            Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        )
    return folders


def _startup_folder_scope(path):
    resolved = path.resolve()
    for variable, scope in (("APPDATA", "user"), ("PROGRAMDATA", "machine")):
        root = os.environ.get(variable)
        if not root:
            continue
        try:
            resolved.relative_to(Path(root).resolve())
            return scope
        except ValueError:
            continue
    return "unknown"


def _registry_startup_items(include_disabled):
    try:
        import winreg
    except ImportError:
        return []
    registry = getattr(winreg, "HKEY_CURRENT_USER", None)
    if registry is None:
        return []
    items = []
    hives = (
        ("HKCU", winreg.HKEY_CURRENT_USER),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE),
    )
    locations = (
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
    )
    for hive_name, hive in hives:
        for key_path in locations:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    index = 0
                    while True:
                        try:
                            name, value, value_type = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                            continue
                        item_id = f"registry:{hive_name}:{key_path}:{name}"
                        items.append(
                            {
                                "id": item_id,
                                "name": name,
                                "enabled": True,
                                "origin": f"{hive_name}\\{key_path}",
                                "command": value,
                                "kind": "registry",
                                "scope": "user" if hive_name == "HKCU" else "machine",
                                "registry_hive": hive_name,
                                "registry_key": key_path,
                                "value_name": name,
                                "data_type": value_type,
                            }
                        )
            except OSError:
                continue
    if include_disabled:
        items.extend(_disabled_registry_startup_items(winreg))
    return items


def _disabled_registry_startup_items(winreg):
    hive = winreg.HKEY_CURRENT_USER
    base_path = r"Software\HardwareDiagnostico\DisabledStartup"
    items = []
    try:
        with winreg.OpenKey(hive, base_path) as key:
            count = winreg.QueryInfoKey(key)[0]
            tokens = [winreg.EnumKey(key, index) for index in range(count)]
    except OSError:
        return items
    for token in tokens:
        try:
            with winreg.OpenKey(hive, base_path + "\\" + token) as key:
                hive_name = winreg.QueryValueEx(key, "HiveName")[0]
                registry_key = winreg.QueryValueEx(key, "RegistryKey")[0]
                value_name = winreg.QueryValueEx(key, "ValueName")[0]
                value = winreg.QueryValueEx(key, "Data")[0]
                value_type = winreg.QueryValueEx(key, "OriginalType")[0]
                items.append(
                    {
                        "id": f"registry-disabled:{token}",
                        "name": value_name,
                        "enabled": False,
                        "origin": f"{hive_name}\\{registry_key}",
                        "command": value,
                        "kind": "registry",
                        "scope": "user" if hive_name == "HKCU" else "machine",
                        "registry_hive": hive_name,
                        "registry_key": registry_key,
                        "value_name": value_name,
                        "data_type": value_type,
                        "backup_token": token,
                    }
                )
        except OSError:
            logger.warning("No se pudo leer una entrada de inicio deshabilitada")
    return items


def _disable_registry_startup(item):
    import winreg

    hives = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }
    hive = hives[item["registry_hive"]]
    token = uuid.uuid4().hex
    backup_path = rf"Software\HardwareDiagnostico\DisabledStartup\{token}"
    with winreg.OpenKey(
        hive, item["registry_key"], 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
    ) as source:
        value, value_type = winreg.QueryValueEx(source, item["value_name"])
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, backup_path, 0, winreg.KEY_SET_VALUE
        ) as backup:
            winreg.SetValueEx(backup, "HiveName", 0, winreg.REG_SZ, item["registry_hive"])
            winreg.SetValueEx(backup, "RegistryKey", 0, winreg.REG_SZ, item["registry_key"])
            winreg.SetValueEx(backup, "ValueName", 0, winreg.REG_SZ, item["value_name"])
            winreg.SetValueEx(backup, "OriginalType", 0, winreg.REG_DWORD, value_type)
            winreg.SetValueEx(backup, "Data", 0, value_type, value)
        try:
            winreg.DeleteValue(source, item["value_name"])
        except OSError:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, backup_path)
            except OSError:
                pass
            raise


def _restore_registry_startup(item):
    import winreg

    hive = (
        winreg.HKEY_CURRENT_USER
        if item["registry_hive"] == "HKCU"
        else winreg.HKEY_LOCAL_MACHINE
    )
    with winreg.CreateKeyEx(
        hive,
        item["registry_key"],
        0,
        winreg.KEY_READ | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            winreg.QueryValueEx(key, item["value_name"])
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("Ya existe un valor con el nombre original.")
        winreg.SetValueEx(
            key,
            item["value_name"],
            0,
            int(item["data_type"]),
            item["command"],
        )
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\HardwareDiagnostico\DisabledStartup",
        0,
        winreg.KEY_WRITE,
    ) as key:
        winreg.DeleteKey(key, item["backup_token"])


def _largest_user_directories(root, entry_limit):
    root_path = Path(root)
    candidates = []
    try:
        children = list(root_path.iterdir())
    except OSError:
        return candidates
    remaining = entry_limit
    for child in children:
        if not child.is_dir() or _is_reparse_path(child):
            continue
        size, remaining = _directory_size(child, remaining)
        candidates.append({"path": str(child), "size_bytes": size})
        if remaining <= 0:
            break
    candidates.sort(key=lambda item: item["size_bytes"], reverse=True)
    return candidates[:10]


def _directory_size(root, entry_limit):
    total = 0
    remaining = entry_limit
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories
            if not _is_reparse_path(Path(current) / name)
        ]
        for filename in filenames:
            if remaining <= 0:
                return total, remaining
            remaining -= 1
            path = Path(current) / filename
            if _is_reparse_path(path):
                continue
            try:
                total += path.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total, remaining


def _get(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return default
    key = key.casefold()
    return next(
        (value for name, value in mapping.items() if str(name).casefold() == key),
        default,
    )


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _current_user():
    try:
        return getpass.getuser()
    except (ImportError, OSError):
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
