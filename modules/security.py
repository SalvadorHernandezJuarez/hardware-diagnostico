"""Read-only Windows security inventory and structured findings."""

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.result import DiagnosticResult
from core.severity import Severity


logger = logging.getLogger("hardware_diagnostico")

SECURITY_SECTIONS = (
    "firewall",
    "defender",
    "bitlocker",
    "windows_update",
    "users",
    "services",
    "configuration",
)
POWERSHELL_TIMEOUT_SECONDS = 20
WINDOWS_UPDATE_TIMEOUT_SECONDS = 12

SECTION_COMMANDS = {
    "firewall": ["Get-NetFirewallProfile"],
    "defender": ["Get-MpComputerStatus", "root/SecurityCenter2 AntivirusProduct"],
    "bitlocker": ["Get-BitLockerVolume"],
    "windows_update": [
        "Win32_OperatingSystem",
        "Microsoft.Update.Session / Search",
        "Get-HotFix",
    ],
    "users": [
        "Get-LocalUser",
        "Get-LocalGroupMember (Administrators SID)",
        "WindowsPrincipal.IsInRole",
    ],
    "services": ["Get-Service / Win32_Service"],
    "configuration": [
        "HKLM UAC policy",
        "Confirm-SecureBootUEFI",
        "Get-Tpm",
    ],
}

_POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$requested = @(__REQUESTED__)
$data = [ordered]@{}
try {
    $os = Get-CimInstance Win32_OperatingSystem | Select-Object `
        Caption, Version, BuildNumber, OSArchitecture
    $data.system = @{Available=($null -ne $os); OS=$os; LastInstalled=$null}
} catch {
    $data.system = @{Available=$false; Error=$_.Exception.Message}
}
try {
    $data.system.LastInstalled = Get-HotFix | Sort-Object InstalledOn -Descending |
        Select-Object -First 1 -ExpandProperty InstalledOn
} catch {}
foreach ($section in @('firewall','defender','bitlocker','windows_update','users','services','configuration')) {
    if ($requested -notcontains $section) { continue }
    try {
        switch ($section) {
            'firewall' {
                $profiles = @(Get-NetFirewallProfile | ForEach-Object {
                    [pscustomobject]@{Name=$_.Name; Enabled=[bool]$_.Enabled}
                })
                $data.firewall = @{Available=$true; Profiles=$profiles; Error=$null}
            }
            'defender' {
                $status = $null
                $products = @()
                try {
                    $status = Get-MpComputerStatus | Select-Object `
                        AntivirusEnabled, RealTimeProtectionEnabled, `
                        AntispywareEnabled, AMServiceEnabled, NISEnabled, `
                        AntivirusSignatureLastUpdated, AntivirusSignatureVersion
                } catch {}
                try {
                    $products = @(Get-CimInstance -Namespace root/SecurityCenter2 `
                        -ClassName AntivirusProduct | ForEach-Object {
                            [pscustomobject]@{
                                DisplayName=$_.displayName
                                ProductState=$_.productState
                            }
                        })
                } catch {}
                $data.defender = @{
                    Available=($null -ne $status)
                    Status=$status
                    OtherAntivirus=@($products | Where-Object {
                        $_.DisplayName -and
                        $_.DisplayName -notmatch 'Microsoft Defender|Windows Defender'
                    })
                    Error=$(if ($null -eq $status) {'Defender no disponible o sin permisos'} else {$null})
                }
            }
            'bitlocker' {
                $volumes = @(Get-BitLockerVolume | ForEach-Object {
                    [pscustomobject]@{
                        MountPoint=$_.MountPoint
                        VolumeType=[string]$_.VolumeType
                        VolumeStatus=[string]$_.VolumeStatus
                        EncryptionPercentage=$_.EncryptionPercentage
                        ProtectionStatus=[string]$_.ProtectionStatus
                        EncryptionMethod=[string]$_.EncryptionMethod
                        LockStatus=[string]$_.LockStatus
                    }
                })
                $data.bitlocker = @{Available=$true; Volumes=$volumes; Error=$null}
            }
            'windows_update' {
                $updates = $null
                $updateError = $null
                try {
                    $session = New-Object -ComObject Microsoft.Update.Session
                    $search = $session.CreateUpdateSearcher().Search(
                        "IsInstalled=0 and IsHidden=0 and Type='Software'"
                    )
                    $updates = @($search.Updates | ForEach-Object {
                        [pscustomobject]@{
                            Title=$_.Title
                            KBArticleIDs=@($_.KBArticleIDs)
                        }
                    })
                } catch {
                    $updateError = $_.Exception.Message
                }
                $data.windows_update = @{
                    Available=$true
                    PendingAvailable=($null -ne $updates)
                    PendingUpdates=@($updates)
                    Error=$updateError
                }
            }
            'users' {
                $localUsers = @(Get-LocalUser | ForEach-Object {
                    [pscustomobject]@{
                        Name=$_.Name
                        Enabled=[bool]$_.Enabled
                        LastLogon=$_.LastLogon
                        PrincipalSource=[string]$_.PrincipalSource
                    }
                })
                $administrators = @()
                $administratorsAvailable = $false
                try {
                    $adminGroup = Get-LocalGroup -SID 'S-1-5-32-544'
                    $administrators = @(Get-LocalGroupMember -Group $adminGroup |
                        ForEach-Object {
                            [pscustomobject]@{
                                Name=$_.Name
                                ObjectClass=[string]$_.ObjectClass
                                PrincipalSource=[string]$_.PrincipalSource
                            }
                        })
                    $administratorsAvailable = $true
                } catch {}
                $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
                $principal = New-Object Security.Principal.WindowsPrincipal($identity)
                $data.users = @{
                    Available=$true
                    CurrentUser=$identity.Name
                    CurrentIsAdmin=$principal.IsInRole(
                        [Security.Principal.WindowsBuiltInRole]::Administrator
                    )
                    LocalUsers=$localUsers
                    Administrators=$administrators
                    AdministratorsAvailable=$administratorsAvailable
                    Error=$null
                }
            }
            'services' {
                $names = @('WinDefend','MpsSvc','wuauserv','wscsvc',
                    'SecurityHealthService','BFE')
                $services = @(Get-Service -Name $names -ErrorAction SilentlyContinue |
                    ForEach-Object {
                        [pscustomobject]@{
                            Name=$_.Name
                            DisplayName=$_.DisplayName
                            Status=[string]$_.Status
                        }
                    })
                $startup = @{}
                try {
                    Get-CimInstance Win32_Service -Filter (
                        "Name='" + ($names -join "' OR Name='") + "'"
                    ) | ForEach-Object {$startup[$_.Name]=$_.StartMode}
                } catch {}
                foreach ($service in $services) {
                    $service | Add-Member -NotePropertyName StartType `
                        -NotePropertyValue $startup[$service.Name] -Force
                }
                $data.services = @{Available=$true; Services=$services; Error=$null}
            }
            'configuration' {
                $uac = $null
                try {
                    $uac = (Get-ItemProperty `
                        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' `
                        -Name EnableLUA).EnableLUA
                } catch {}
                $secureBoot = $null
                try {$secureBoot = [bool](Confirm-SecureBootUEFI)} catch {}
                $firmware = $null
                try {
                    $firmware = (Get-ComputerInfo -Property BiosFirmwareType).BiosFirmwareType.ToString()
                } catch {}
                $tpm = $null
                try {
                    $tpmResult = Get-Tpm
                    $tpm = [pscustomobject]@{
                        Present=[bool]$tpmResult.TpmPresent
                        Ready=[bool]$tpmResult.TpmReady
                        Enabled=[bool]$tpmResult.TpmEnabled
                        Activated=[bool]$tpmResult.TpmActivated
                        ManufacturerId=$tpmResult.ManufacturerId
                        ManufacturerVersion=$tpmResult.ManufacturerVersion
                    }
                } catch {}
                $data.configuration = @{
                    Available=$true
                    UACEnabled=$(if ($null -ne $uac) {[bool]$uac} else {$null})
                    SecureBoot=$secureBoot
                    FirmwareType=$firmware
                    TPM=$tpm
                    Error=$null
                }
            }
        }
    } catch {
        $data[$section] = @{
            Available=$false
            Error=$_.Exception.Message
        }
    }
}
[pscustomobject]$data | ConvertTo-Json -Depth 9 -Compress
"""


@dataclass
class SecurityCheck:
    name: str
    status: Optional[bool]
    severity: Severity
    evidence: Any = field(default_factory=dict)
    description: str = ""


@dataclass
class SecurityAuditResult:
    timestamp: str
    data: Dict[str, Any]
    checks: List[SecurityCheck]
    findings: List[DiagnosticResult]
    severity: Severity
    commands: List[str]

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "data": self.data,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "severity": check.severity.label,
                    "evidence": check.evidence,
                    "description": check.description,
                }
                for check in self.checks
            ],
            "findings": [finding.to_dict() for finding in self.findings],
            "severity": self.severity.label,
            "commands": self.commands,
        }


class SecurityAuditor:
    """Collect Windows security posture without changing system settings."""

    def __init__(self, powershell_query=None):
        self._powershell_query = powershell_query

    def audit(self, sections=None):
        sections = tuple(SECURITY_SECTIONS if sections is None else sections)
        invalid = set(sections).difference(SECURITY_SECTIONS)
        if invalid:
            raise ValueError(f"Secciones de seguridad no válidas: {sorted(invalid)}")
        if "configuration" in sections:
            sections = tuple(SECURITY_SECTIONS)

        query_sections = tuple(
            section for section in sections if section != "windows_update"
        )
        rows = self._query(
            _powershell_script(query_sections),
            POWERSHELL_TIMEOUT_SECONDS,
        ) or {}
        if "windows_update" in sections:
            update_rows = self._query(
                _powershell_script(("windows_update",)),
                WINDOWS_UPDATE_TIMEOUT_SECONDS,
            )
            update_data = _normalize_section(_get(update_rows, "windows_update"))
            if update_rows is None:
                update_data["pending_available"] = False
                update_data["error"] = "Consulta de Windows Update no disponible"
            system_data = _get(rows, "system")
            if isinstance(system_data, dict):
                update_data["os"] = _json_safe(_get(system_data, "OS"))
                update_data["last_installed"] = _json_safe(
                    _get(system_data, "LastInstalled")
                )
                if update_data.get("available") is False:
                    update_data["available"] = bool(
                        _get(system_data, "Available", default=False)
                    )
            rows["windows_update"] = update_data
        data = {
            section: _normalize_section(_get(rows, section))
            for section in sections
        }
        findings = []
        checks = []
        for section in sections:
            self._evaluate_section(section, data[section], findings, checks)
        if not findings:
            findings.append(_finding(
                "SEC_AUDIT_INCOMPLETE",
                "SEGURIDAD",
                "No hubo datos suficientes para evaluar seguridad",
                Severity.INFORMATION,
                "Las consultas de seguridad no devolvieron evidencia utilizable.",
                {"sections": list(sections)},
                "No disponible",
                source="PowerShell",
            ))
        actionable = [
            finding.severity for finding in findings
            if finding.severity >= Severity.ALERT
        ]
        if actionable:
            severity = max(actionable)
        elif any(finding.severity == Severity.NORMAL for finding in findings):
            severity = Severity.NORMAL
        else:
            severity = Severity.INFORMATION
        return SecurityAuditResult(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            data=data,
            checks=checks,
            findings=findings,
            severity=severity,
            commands=[
                command
                for section in sections
                for command in SECTION_COMMANDS[section]
            ],
        )

    def _query(self, script, timeout):
        if self._powershell_query is None:
            return _powershell_json(script, timeout=timeout)
        try:
            return self._powershell_query(script)
        except Exception:
            logger.exception("Error consultando datos de seguridad con PowerShell")
            return None

    @staticmethod
    def _evaluate_section(section, data, findings, checks):
        if not data.get("available") and not (
            section == "defender" and data.get("other_antivirus")
            or section == "windows_update"
            and "pending_available" in data
        ):
            _check(
                checks, section.replace("_", " ").title(), None,
                Severity.INFORMATION, {"error": data.get("error")},
                "No disponible",
            )
            return
        evaluators = {
            "firewall": _evaluate_firewall,
            "defender": _evaluate_defender,
            "bitlocker": _evaluate_bitlocker,
            "windows_update": _evaluate_updates,
            "users": _evaluate_users,
            "services": _evaluate_services,
            "configuration": _evaluate_configuration,
        }
        evaluators[section](data, findings, checks)


def _powershell_script(sections):
    requested = ",".join(f"'{section}'" for section in sections)
    return _POWERSHELL_SCRIPT.replace("__REQUESTED__", requested)


def _powershell_json(script, timeout=POWERSHELL_TIMEOUT_SECONDS):
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        logger.info("PowerShell no disponible para auditoría de seguridad")
        return None
    try:
        result = subprocess.run(
            [
                executable, "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "Consulta de seguridad PowerShell agotó el tiempo límite (%s s)",
            timeout,
        )
        return None
    except (OSError, subprocess.SubprocessError):
        logger.exception("No se pudo consultar PowerShell para seguridad")
        return None
    if result.returncode != 0 or not result.stdout.strip():
        logger.warning(
            "Consulta de seguridad PowerShell no disponible | codigo=%s | error=%s",
            result.returncode,
            (result.stderr or "").strip()[-1000:],
        )
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("PowerShell devolvió JSON de seguridad no válido")
        return None
    return value if isinstance(value, dict) else None


def _normalize_section(value):
    if not isinstance(value, dict):
        return {"available": False, "error": "No disponible"}
    return {
        "available": bool(_get(value, "Available", default=False)),
        "error": _get(value, "Error"),
        **{
            _snake_case(key): _json_safe(item)
            for key, item in value.items()
            if key.casefold() not in ("available", "error")
        },
    }


def _evaluate_firewall(data, findings, checks):
    profiles = _records(data.get("profiles"))
    if not profiles:
        _unavailable(findings, checks, "firewall", "No se reportaron perfiles.")
        return
    disabled = []
    for profile in profiles:
        name = _get(profile, "Name", default="Perfil")
        enabled = _as_bool(_get(profile, "Enabled"))
        if enabled is False:
            disabled.append(name)
            findings.append(_finding(
                "SEC_FIREWALL_DISABLED",
                "FIREWALL",
                f"Firewall desactivado en perfil {name}",
                Severity.ALERT,
                "Windows reporta desactivado este perfil de firewall.",
                profile,
                False,
                True,
                "Revisar el perfil en Seguridad de Windows o con el administrador del equipo.",
            ))
    statuses = [_as_bool(_get(profile, "Enabled")) for profile in profiles]
    status = (
        False if disabled
        else True if statuses and all(value is True for value in statuses)
        else None
    )
    _check(
        checks, "Firewall", status,
        Severity.ALERT if disabled else (
            Severity.NORMAL if status is True else Severity.INFORMATION
        ),
        {"profiles": profiles, "disabled_profiles": disabled},
        "Uno o más perfiles están desactivados."
        if disabled else "Los perfiles reportados están activos."
        if status is True else "El estado de uno o más perfiles no está disponible.",
    )
    if status is True:
        findings.append(_finding(
            "SEC_FIREWALL_ENABLED", "FIREWALL",
            "Perfiles de firewall activos", Severity.NORMAL,
            "Todos los perfiles de firewall reportados están habilitados.",
            {"profiles": profiles},
            True, True,
        ))


def _evaluate_defender(data, findings, checks):
    status = data.get("status")
    other_antivirus = _records(data.get("other_antivirus"))
    if not data.get("available") or not isinstance(status, dict):
        reason = data.get("error") or "Defender no disponible o administrado por otro antivirus."
        if other_antivirus:
            names = [
                str(_get(product, "DisplayName", default="Antivirus registrado"))
                for product in other_antivirus
            ]
            reason = (
                "Defender no disponible; Windows registra otro producto antivirus "
                f"({', '.join(names)}). Su estado activo no se pudo confirmar."
            )
        _unavailable(
            findings, checks, "Windows Defender",
            reason,
            {"other_antivirus": other_antivirus},
        )
        if other_antivirus:
            checks[-1].description = reason
        return
    antivirus_enabled = _as_bool(_get(status, "AntivirusEnabled"))
    realtime_enabled = _as_bool(_get(status, "RealTimeProtectionEnabled"))
    antispyware_enabled = _as_bool(_get(status, "AntispywareEnabled"))
    evidence = {
        "status": status,
        "other_antivirus": other_antivirus,
    }
    if antivirus_enabled is False:
        severity = Severity.INFORMATION if other_antivirus else Severity.ALERT
        findings.append(_finding(
            "SEC_DEFENDER_DISABLED",
            "WINDOWS DEFENDER",
            "Microsoft Defender no está activo",
            severity,
            "Windows reporta AntivirusEnabled como falso."
            + (
                " Hay otro producto antivirus registrado; esto no confirma que el equipo carezca de antivirus."
                if other_antivirus else
                " No se pudo confirmar otro antivirus activo."
            ),
            evidence,
            False,
            True,
            "Verificar el proveedor antivirus activo en Seguridad de Windows.",
            confidence="MEDIA" if other_antivirus else "ALTA",
        ))
    if antivirus_enabled is True and realtime_enabled is False:
        findings.append(_finding(
            "SEC_REALTIME_PROTECTION_DISABLED",
            "WINDOWS DEFENDER",
            "Protección en tiempo real desactivada",
            Severity.ALERT,
            "Defender está habilitado, pero Windows reporta desactivada la protección en tiempo real.",
            evidence,
            False,
            True,
            "Revisar Protección contra virus y amenazas en Seguridad de Windows.",
        ))
    if antivirus_enabled is True and antispyware_enabled is False:
        findings.append(_finding(
            "SEC_DEFENDER_THREAT_PROTECTION_DISABLED",
            "WINDOWS DEFENDER",
            "Protección antispyware de Defender desactivada",
            Severity.ALERT,
            "Windows reporta AntispywareEnabled como falso.",
            evidence,
            False,
            True,
            "Revisar las opciones de protección contra virus y amenazas.",
        ))
    _check(
        checks,
        "Windows Defender",
        antivirus_enabled,
        Severity.NORMAL if antivirus_enabled else (
            Severity.ALERT if not other_antivirus else Severity.INFORMATION
        ),
        evidence,
        "Defender reporta antivirus activo."
        if antivirus_enabled else "Defender está desactivado o sustituido por otro proveedor.",
    )
    _check(
        checks,
        "Protección en tiempo real",
        realtime_enabled if antivirus_enabled is True else None,
        Severity.ALERT if realtime_enabled is False and antivirus_enabled is True
        else Severity.NORMAL if realtime_enabled is True
        else Severity.INFORMATION,
        {"enabled": realtime_enabled},
        "Activa" if realtime_enabled is True else (
            "Desactivada" if realtime_enabled is False and antivirus_enabled is True
            else "No disponible o Defender no es el proveedor activo"
        ),
    )
    if antivirus_enabled and realtime_enabled is not False:
        findings.append(_finding(
            "SEC_DEFENDER_ACTIVE", "WINDOWS DEFENDER",
            "Antivirus de Microsoft Defender activo", Severity.NORMAL,
            "Windows reporta el antivirus de Defender habilitado.",
            evidence, True, True,
        ))
    signature_date = _get(status, "AntivirusSignatureLastUpdated")
    _check(
        checks, "Firmas de Defender", None if not signature_date else True,
        Severity.INFORMATION,
        {"last_updated": signature_date},
        "Fecha de actualización disponible." if signature_date else "No disponible",
    )


def _evaluate_bitlocker(data, findings, checks):
    volumes = _records(data.get("volumes"))
    if not volumes:
        _unavailable(findings, checks, "BitLocker", "No se reportaron volúmenes.")
        return
    known = []
    unprotected = []
    for volume in volumes:
        mount = _get(volume, "MountPoint", default="Unidad desconocida")
        protection = str(_get(volume, "ProtectionStatus", default="")).casefold()
        conversion = str(_get(volume, "VolumeStatus", default="")).casefold()
        encrypted = _as_float(_get(volume, "EncryptionPercentage"))
        is_protected = protection in ("on", "1", "protected")
        is_definitely_unprotected = (
            protection in ("off", "0", "unprotected")
            and (
                conversion in ("fullydecrypted", "fully decrypted")
                or encrypted == 0
            )
        )
        if is_protected:
            known.append(True)
            continue
        if not is_definitely_unprotected:
            known.append(None)
            continue
        known.append(False)
        unprotected.append(mount)
        findings.append(_finding(
            "SEC_BITLOCKER_DISABLED",
            "BITLOCKER",
            f"{mount} no reporta protección BitLocker activa",
            Severity.INFORMATION,
            "El volumen no reporta protección BitLocker activa; cifrado no habilitado no confirma por sí mismo una vulnerabilidad.",
            volume,
            {"protection_status": protection, "volume_status": conversion},
            {"protection_status": "On", "encryption_percent": 100},
            "Considerar las necesidades de cifrado del equipo y las políticas de la organización.",
            confidence="MEDIA",
        ))
    status = (
        False if False in known
        else True if known and all(value is True for value in known)
        else None
    )
    _check(
        checks, "BitLocker", status,
        Severity.INFORMATION if unprotected or status is None else Severity.NORMAL,
        {"volumes": volumes, "unprotected_volumes": unprotected},
        "Hay volúmenes sin protección activa."
        if unprotected else "Los volúmenes reportados están protegidos."
        if status is True else "El estado de protección no está disponible.",
    )
    if status is True:
        findings.append(_finding(
            "SEC_BITLOCKER_PROTECTED", "BITLOCKER",
            "Volúmenes reportados protegidos", Severity.NORMAL,
            "Todos los volúmenes consultados reportan protección activa.",
            {"volumes": volumes}, True, True,
        ))


def _evaluate_updates(data, findings, checks):
    updates = _records(data.get("pending_updates"))
    os_info = data.get("os") or {}
    if data.get("pending_available") is not True:
        _check(
            checks, "Windows Update", None, Severity.INFORMATION,
            {"os": os_info, "error": data.get("error")},
            "Estado de actualizaciones pendientes: No disponible",
        )
        findings.append(_finding(
            "SEC_UPDATES_UNAVAILABLE", "WINDOWS UPDATE",
            "No se pudo determinar el estado de Windows Update",
            Severity.INFORMATION,
            "La consulta de actualizaciones pendientes no estuvo disponible.",
            {"os": os_info, "error": data.get("error")},
            source="Windows Update Agent",
        ))
        return
    pending = len(updates)
    findings.append(_finding(
        "SEC_UPDATES_PENDING" if pending else "SEC_UPDATES_CURRENT",
        "WINDOWS UPDATE",
        "Actualizaciones pendientes" if pending else "No se detectaron actualizaciones pendientes",
        Severity.ALERT if pending else Severity.NORMAL,
        f"Windows Update reportó {pending} actualización(es) de software pendientes.",
        {"os": os_info, "pending_count": pending, "updates": updates},
        pending,
        0,
        "Revisar Windows Update e instalar actualizaciones según la política aplicable."
        if pending else "",
    ))
    _check(
        checks, "Windows Update", pending == 0,
        Severity.ALERT if pending else Severity.NORMAL,
        {"pending_count": pending, "updates": updates, "os": os_info},
        f"{pending} actualización(es) pendiente(s)." if pending
        else "No se reportan actualizaciones pendientes.",
    )


def _evaluate_users(data, findings, checks):
    current_admin = _as_bool(data.get("current_is_admin"))
    administrators = _records(data.get("administrators"))
    if current_admin is None:
        _unavailable(findings, checks, "Usuarios", "No se pudo consultar el usuario actual.")
        return
    local_users = _records(data.get("local_users"))
    admin_names = [
        str(_get(account, "Name", default=""))
        for account in administrators
    ]
    administrators_available = data.get("administrators_available") is True
    _check(
        checks, "Usuarios", True, Severity.INFORMATION,
        {
            "current_user": data.get("current_user"),
            "current_is_admin": current_admin,
            "administrators": (
                administrators if data.get("administrators_available") else None
            ),
            "local_users": local_users,
        },
        "Inventario local disponible.",
    )
    _check(
        checks, "Administradores locales",
        True if administrators_available else None,
        Severity.INFORMATION,
        {"members": administrators if administrators_available else None},
        "Miembros consultados." if administrators_available else "No disponible",
    )
    if current_admin:
        findings.append(_finding(
            "SEC_ADMIN_USER", "USUARIOS",
            "La sesión actual pertenece al grupo Administradores",
            Severity.INFORMATION,
            "La sesión tiene privilegios administrativos; esto no implica por sí solo una configuración insegura.",
            {
                "current_user": data.get("current_user"),
                "administrators": admin_names if administrators_available else None,
            },
            True, False,
            "Usar una cuenta estándar para tareas cotidianas cuando sea práctico.",
        ))
    if administrators_available and len(administrators) > 1:
        findings.append(_finding(
            "SEC_ADDITIONAL_ADMIN_USERS", "USUARIOS",
            "Se encontraron varias cuentas administrativas",
            Severity.INFORMATION,
            "Se muestran miembros del grupo integrado Administradores; valide que cada acceso sea esperado.",
            {"administrators": admin_names},
            len(administrators), "Solo cuentas autorizadas",
            "Revisar periódicamente los miembros del grupo Administradores.",
        ))
    findings.append(_finding(
        "SEC_USERS_REVIEWED", "USUARIOS",
        "Inventario básico de usuarios disponible",
        Severity.NORMAL if administrators_available else Severity.INFORMATION,
        "Se consultaron el usuario actual y las cuentas locales; "
        "el grupo Administradores está disponible."
        if administrators_available else
        "Se consultaron el usuario actual y las cuentas locales; "
        "no se obtuvo la lista del grupo Administradores.",
        {
            "local_users_count": len(local_users),
            "administrators": admin_names if administrators_available else None,
        },
        True, True,
    ))


def _evaluate_services(data, findings, checks):
    services = _records(data.get("services"))
    if not services:
        _unavailable(findings, checks, "Servicios", "No se reportaron servicios.")
        return
    relevant = {"mpssvc", "bfe", "windefend", "wscsvc", "securityhealthservice", "wuauserv"}
    services = [
        service for service in services
        if str(_get(service, "Name", default="")).casefold() in relevant
    ]
    _check(
        checks, "Servicios", True, Severity.INFORMATION,
        {"services": services},
        "Se consultaron los servicios de seguridad disponibles.",
    )
    findings.append(_finding(
        "SEC_SERVICES_REVIEWED", "SERVICIOS",
        "Servicios de seguridad consultados", Severity.NORMAL,
        "Se consultaron estados de firewall, Defender, actualización y centro de seguridad.",
        {"services": services}, True, True,
    ))


def _evaluate_configuration(data, findings, checks):
    uac = _as_bool(data.get("uac_enabled"))
    secure_boot = _as_bool(data.get("secure_boot"))
    firmware = str(data.get("firmware_type") or "").casefold()
    tpm = data.get("tpm") if isinstance(data.get("tpm"), dict) else None
    configuration = {
        "uac_enabled": uac,
        "secure_boot": secure_boot,
        "firmware_type": data.get("firmware_type"),
        "tpm": tpm,
    }
    if uac is False:
        findings.append(_finding(
            "SEC_UAC_DISABLED", "UAC",
            "Control de cuentas de usuario desactivado", Severity.ALERT,
            "Windows reporta EnableLUA=0.",
            {"uac_enabled": uac}, False, True,
            "Revisar la configuración de Control de cuentas de usuario.",
        ))
    if secure_boot is False and "uefi" in firmware:
        findings.append(_finding(
            "SEC_SECURE_BOOT_DISABLED", "SECURE BOOT",
            "Secure Boot desactivado en firmware UEFI", Severity.ALERT,
            "El firmware reporta UEFI y Confirm-SecureBootUEFI devolvió falso.",
            configuration, False, True,
            "Verificar compatibilidad del sistema antes de cambiar la configuración UEFI.",
        ))
    if tpm is not None and _as_bool(_get(tpm, "Present")) is False:
        findings.append(_finding(
            "SEC_TPM_UNAVAILABLE", "TPM",
            "Windows no detectó un TPM", Severity.INFORMATION,
            "No se detectó TPM; puede no estar presente, habilitado o disponible para Windows.",
            {"tpm": tpm}, False, True,
            "Consultar firmware y documentación del equipo; no todos los sistemas requieren TPM.",
            confidence="BAJA",
        ))
    secure_boot_applicable = "uefi" in firmware
    configuration_status = (
        False if uac is False or (
            secure_boot is False and secure_boot_applicable
        )
        else True if uac is True and (
            secure_boot is True or (
                secure_boot is None and not secure_boot_applicable
            )
        )
        else None
    )
    _check(
        checks, "UAC", uac,
        Severity.ALERT if uac is False else (
            Severity.NORMAL if uac is True else Severity.INFORMATION
        ),
        {"uac_enabled": uac},
        "Habilitado" if uac is True else (
            "Desactivado" if uac is False else "No disponible"
        ),
    )
    _check(
        checks, "Secure Boot",
        secure_boot if secure_boot_applicable else None,
        Severity.ALERT if secure_boot is False and secure_boot_applicable
        else Severity.NORMAL if secure_boot is True
        else Severity.INFORMATION,
        {"secure_boot": secure_boot, "firmware_type": data.get("firmware_type")},
        "Habilitado" if secure_boot is True else (
            "Desactivado" if secure_boot is False and secure_boot_applicable
            else "No disponible o no aplicable"
        ),
    )
    tpm_present = _as_bool(_get(tpm, "Present")) if tpm else None
    _check(
        checks, "TPM", tpm_present,
        Severity.NORMAL if tpm_present else Severity.INFORMATION,
        {"tpm": tpm},
        "Detectado" if tpm_present else "No disponible",
    )
    _check(
        checks, "Configuración de seguridad", configuration_status,
        Severity.ALERT if (
            uac is False or (secure_boot is False and "uefi" in firmware)
        ) else Severity.INFORMATION if configuration_status is None
        else Severity.NORMAL,
        configuration,
        "Una configuración comprobable requiere revisión."
        if configuration_status is False else "Configuración consultada."
        if configuration_status is True
        else "No se pudo determinar la configuración completa.",
    )
    if configuration_status is True:
        findings.append(_finding(
            "SEC_CONFIGURATION_REVIEWED", "CONFIGURACIÓN",
            "Configuración básica consultada", Severity.NORMAL,
            "UAC y Secure Boot reportan habilitados.",
            configuration, True, True,
        ))


def _unavailable(findings, checks, name, reason, evidence=None):
    _check(
        checks, name, None, Severity.INFORMATION,
        evidence or {"reason": reason},
        "No disponible",
    )
    findings.append(_finding(
        f"SEC_{name.upper().replace(' ', '_')}_UNAVAILABLE",
        name.upper(),
        f"{name}: información no disponible",
        Severity.INFORMATION,
        reason,
        evidence or {"reason": reason},
        source="PowerShell / Windows",
        confidence="BAJA",
    ))


def _check(checks, name, status, severity, evidence, description):
    checks.append(SecurityCheck(name, status, severity, evidence, description))


def _finding(code, component, title, severity, description, evidence,
             current_value=None, expected_value=None, recommendation="",
             source="PowerShell / Windows", confidence="ALTA"):
    logger.info("Hallazgo de seguridad | codigo=%s | severidad=%s", code, severity.label)
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
        confidence=confidence,
        source=source,
        rule_id=code,
    )


def _records(value):
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _get(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return default
    key = _snake_case(key).casefold()
    return next(
        (
            value for name, value in mapping.items()
            if _snake_case(name).casefold() == key
        ),
        default,
    )


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        if value.casefold() in ("true", "1", "enabled", "on"):
            return True
        if value.casefold() in ("false", "0", "disabled", "off"):
            return False
    return None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snake_case(value):
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(value))
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def _json_safe(value):
    if isinstance(value, dict):
        return {_snake_case(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
