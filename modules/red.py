"""Read-only Windows network diagnostics and explicitly confirmed actions."""

import ipaddress
import json
import logging
import getpass
import re
import shutil
import socket
import struct
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil

from core.result import DiagnosticResult
from core.severity import Severity


logger = logging.getLogger("hardware_diagnostico")

NETWORK_THRESHOLDS = {
    "ping_count": 4,
    "ping_timeout_ms": 1500,
    "traceroute_max_hops": 20,
    "traceroute_timeout_ms": 1000,
    "dns_timeout_seconds": 2.0,
    "latency_alert_ms": 150.0,
    "packet_loss_alert_percent": 10.0,
}
DIAGNOSTIC_DOMAINS = ("example.com", "www.microsoft.com")
EXTERNAL_PROBES = (("1.1.1.1", 443), ("8.8.8.8", 443))


def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(command, timeout=10):
    try:
        completed = subprocess.run(
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
            "return_code": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "error": None,
        }
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning(
            "Comando de red falló | comando=%s | error=%s",
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


def _powershell_json(script, timeout=12):
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        logger.info("PowerShell no disponible para inventario de red")
        return None
    result = _run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        timeout=timeout,
    )
    if result["return_code"] != 0 or not result["stdout"].strip():
        return None
    try:
        value = json.loads(result["stdout"])
        if isinstance(value, list):
            return value
        return [value] if value else []
    except json.JSONDecodeError:
        logger.warning("PowerShell devolvió JSON de red no válido")
        return None


@dataclass
class NetworkAdapter:
    name: str
    description: Optional[str] = None
    status: str = "No disponible"
    mac_address: Optional[str] = None
    speed_mbps: Optional[float] = None
    adapter_type: Optional[str] = None
    ipv4: List[str] = field(default_factory=list)
    ipv6: List[str] = field(default_factory=list)
    subnet_masks: List[str] = field(default_factory=list)
    prefix_lengths: List[int] = field(default_factory=list)
    gateways: List[str] = field(default_factory=list)
    dns_servers: List[str] = field(default_factory=list)
    dhcp_enabled: Optional[bool] = None
    dhcp_server: Optional[str] = None
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    signal_percent: Optional[int] = None
    channel: Optional[int] = None
    wifi_radio: Optional[str] = None
    interface_index: Optional[int] = None
    is_physical: Optional[bool] = None
    is_up: bool = False
    source: str = "psutil"


@dataclass
class NetworkConfiguration:
    hostname: str
    adapters: List[NetworkAdapter]
    default_gateway: Optional[str]
    dns_servers: List[str]
    apipa_addresses: List[str]
    valid_ipv4: bool
    timestamp: str = field(default_factory=_timestamp)


@dataclass
class PingResult:
    destination: str
    packets_sent: int
    packets_received: int
    packets_lost: int
    packet_loss_percent: float
    minimum_ms: Optional[float]
    maximum_ms: Optional[float]
    average_ms: Optional[float]
    samples_ms: List[float] = field(default_factory=list)
    source: str = "ping"
    error: Optional[str] = None
    findings: List[DiagnosticResult] = field(default_factory=list)
    timestamp: str = field(default_factory=_timestamp)

    def to_dict(self):
        result = asdict(self)
        result["findings"] = [finding.to_dict() for finding in self.findings]
        return result


@dataclass
class DnsResult:
    configured_servers: List[str]
    domain: str
    resolution_succeeded: Optional[bool]
    resolved_addresses: List[str] = field(default_factory=list)
    server_responses: Dict[str, Optional[bool]] = field(default_factory=dict)
    source: str = "socket.getaddrinfo / DNS UDP"
    error: Optional[str] = None
    timestamp: str = field(default_factory=_timestamp)


@dataclass
class GatewayResult:
    address: Optional[str]
    reachable: Optional[bool]
    ping: Optional[PingResult] = None
    source: str = "route table / ping"
    timestamp: str = field(default_factory=_timestamp)


@dataclass
class NetworkCheck:
    name: str
    status: Optional[bool]
    severity: Severity
    evidence: Any = field(default_factory=dict)
    description: str = ""


@dataclass
class NetworkActionResult:
    action: str
    success: bool
    commands: List[str]
    outputs: List[Dict[str, Any]]
    user: str
    timestamp: str = field(default_factory=_timestamp)
    requires_restart: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class NetworkDiagnosticResult:
    timestamp: str
    adapters: List[NetworkAdapter]
    configuration: NetworkConfiguration
    gateway: GatewayResult
    dns: DnsResult
    internet_reachable: Optional[bool]
    internet_probe: Optional[str]
    ping: Optional[PingResult]
    traceroute: Optional[dict]
    checks: List[NetworkCheck]
    findings: List[DiagnosticResult]
    severity: Severity
    diagnosis: str
    recommendation: str
    source: str = "psutil / PowerShell / ping / DNS"

    def to_dict(self):
        gateway = asdict(self.gateway)
        gateway["ping"] = self.gateway.ping.to_dict() if self.gateway.ping else None
        return {
            "timestamp": self.timestamp,
            "adapters": [asdict(adapter) for adapter in self.adapters],
            "configuration": asdict(self.configuration),
            "gateway": gateway,
            "dns": asdict(self.dns),
            "internet_reachable": self.internet_reachable,
            "internet_probe": self.internet_probe,
            "ping": self.ping.to_dict() if self.ping else None,
            "traceroute": self.traceroute,
            "checks": [
                {
                    **asdict(check),
                    "severity": check.severity.label,
                }
                for check in self.checks
            ],
            "findings": [finding.to_dict() for finding in self.findings],
            "severity": self.severity.label,
            "diagnosis": self.diagnosis,
            "recommendation": self.recommendation,
            "source": self.source,
            "commands": [
                "Get-NetIPConfiguration / Get-NetAdapter",
                "ping -n 1 -w <timeout> <destino> (repetido)",
                "DNS UDP/53 + socket.getaddrinfo",
                "socket TCP para conectividad externa",
            ],
        }


class NetworkDiagnostics:
    """Collect network facts and assess connectivity layer by layer."""

    def __init__(self, command_runner=None, powershell_query=None, resolver=None):
        self._run = command_runner or _run
        self._powershell_query = powershell_query or _powershell_json
        self._resolver = resolver or socket.getaddrinfo

    def get_adapters(self):
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "$items=Get-NetAdapter | ForEach-Object { "
            "$a=$_; $c=Get-NetIPConfiguration -InterfaceIndex $a.InterfaceIndex "
            "-ErrorAction SilentlyContinue; "
            "$i4=Get-NetIPInterface -InterfaceIndex $a.InterfaceIndex "
            "-AddressFamily IPv4; "
            "$dhcp=(Get-CimInstance Win32_NetworkAdapterConfiguration "
            "-Filter ('InterfaceIndex=' + $a.InterfaceIndex)); "
            "[pscustomobject]@{"
            "Name=$a.Name; InterfaceIndex=$a.InterfaceIndex; "
            "Description=$a.InterfaceDescription; Status=$a.Status; "
            "MacAddress=$a.MacAddress; LinkSpeed=$a.LinkSpeed; "
            "Physical=$a.HardwareInterface; "
            "IPv4=@($c.IPv4Address | ForEach-Object {$_.IPAddress}); "
            "IPv4Prefix=@($c.IPv4Address | ForEach-Object {$_.PrefixLength}); "
            "IPv6=@($c.IPv6Address | ForEach-Object {$_.IPAddress}); "
            "IPv6Prefix=@($c.IPv6Address | ForEach-Object {$_.PrefixLength}); "
            "Gateway=@($c.IPv4DefaultGateway | ForEach-Object {$_.NextHop}); "
            "DNS=@((Get-DnsClientServerAddress -InterfaceIndex "
            "$a.InterfaceIndex -ErrorAction SilentlyContinue).ServerAddresses "
            "| Where-Object {$_}); DhcpEnabled=$i4.Dhcp; "
            "DhcpServer=$dhcp.DHCPServer"
            "} }; $items | ConvertTo-Json -Depth 5 -Compress"
        )
        system_rows = self._powershell_query(script)
        system_by_name = {}
        if system_rows:
            for row in system_rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("Name")
                if name:
                    system_by_name[str(name).casefold()] = row

        try:
            addresses = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
        except (OSError, psutil.Error):
            logger.exception("No se pudieron enumerar interfaces de red")
            addresses, stats = {}, {}

        adapters = []
        names = list(dict.fromkeys([*addresses.keys(), *[
            str(row.get("Name"))
            for row in (system_rows or [])
            if isinstance(row, dict) and row.get("Name")
        ]]))
        for name in names:
            row = system_by_name.get(name.casefold(), {})
            iface_addresses = addresses.get(name, [])
            stat = stats.get(name)
            ipv4, ipv6, masks = [], [], []
            mac_address = None
            for address in iface_addresses:
                if address.family == socket.AF_INET:
                    ipv4.append(address.address)
                    if address.netmask:
                        masks.append(address.netmask)
                elif address.family == socket.AF_INET6:
                    ipv6.append(address.address.split("%", 1)[0])
                elif getattr(psutil, "AF_LINK", object()) == address.family:
                    mac_address = address.address or None

            ipv4.extend(_list(row.get("IPv4")))
            ipv6.extend(_list(row.get("IPv6")))
            configured_dns = _list(row.get("DNS"))
            gateways = _list(row.get("Gateway"))
            dhcp_value = row.get("DhcpEnabled")
            if isinstance(dhcp_value, str):
                dhcp_enabled = dhcp_value.casefold() in ("enabled", "true", "1")
            elif isinstance(dhcp_value, bool):
                dhcp_enabled = dhcp_value
            else:
                dhcp_enabled = None
            link_speed = _parse_speed(row.get("LinkSpeed"))
            speed_mbps = link_speed or (stat.speed if stat and stat.speed else None)
            status_value = str(row.get("Status") or "").casefold()
            is_up = (
                status_value in ("up", "connected")
                if status_value
                else bool(stat and stat.isup)
            )
            description = row.get("Description")
            adapter_type = _adapter_type(
                name, str(description or ""), str(row.get("Status") or "")
            )
            adapters.append(
                NetworkAdapter(
                    name=name,
                    description=description,
                    status=(
                        "Conectado" if is_up else "Desconectado"
                        if stat or row.get("Status") else "No disponible"
                    ),
                    mac_address=row.get("MacAddress") or mac_address,
                    speed_mbps=speed_mbps,
                    adapter_type=adapter_type,
                    ipv4=list(dict.fromkeys(ipv4)),
                    ipv6=list(dict.fromkeys(ipv6)),
                    subnet_masks=masks,
                    prefix_lengths=[
                        int(value) for value in _list(row.get("IPv4Prefix"))
                        if str(value).isdigit()
                    ],
                    gateways=gateways,
                    dns_servers=configured_dns,
                    dhcp_enabled=dhcp_enabled,
                    dhcp_server=row.get("DhcpServer"),
                    interface_index=_as_int(row.get("InterfaceIndex")),
                    is_physical=(
                        row.get("Physical")
                        if isinstance(row.get("Physical"), bool)
                        else None
                    ),
                    is_up=is_up,
                    source="PowerShell + psutil" if row else "psutil",
                )
            )

        wifi = self._wifi_details()
        for adapter in adapters:
            if adapter.adapter_type == "Wi-Fi":
                adapter.ssid = wifi.get("ssid")
                adapter.bssid = wifi.get("bssid")
                adapter.signal_percent = wifi.get("signal_percent")
                adapter.channel = wifi.get("channel")
                adapter.wifi_radio = wifi.get("radio_type")
        return adapters

    def _wifi_details(self):
        if not shutil.which("netsh.exe") and not shutil.which("netsh"):
            return {}
        result = self._run(["netsh", "wlan", "show", "interfaces"], timeout=6)
        output = result.get("stdout", "")
        if result.get("return_code") != 0 or not output:
            return {}
        values = {}
        patterns = {
            "ssid": r"^\s*SSID\s*:\s*(.+?)\s*$",
            "bssid": r"^\s*BSSID\s*:\s*(.+?)\s*$",
            "signal": r"^\s*(?:Signal|Señal)\s*:\s*(\d+)\s*%",
            "channel": r"^\s*(?:Channel|Canal)\s*:\s*(\d+)",
            "radio_type": r"^\s*(?:Radio type|Tipo de radio)\s*:\s*(.+?)\s*$",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
            if match:
                values[key] = match.group(1).strip()
        return {
            "ssid": values.get("ssid"),
            "bssid": values.get("bssid"),
            "signal_percent": _as_int(values.get("signal")),
            "channel": _as_int(values.get("channel")),
            "radio_type": values.get("radio_type"),
        }

    def get_configuration(self):
        adapters = self.get_adapters()
        connected = [
            adapter for adapter in adapters
            if adapter.is_up and adapter.is_physical is not False
            and _is_network_adapter(adapter)
        ]
        gateway = next(
            (item for adapter in connected for item in adapter.gateways), None
        )
        dns_servers = list(dict.fromkeys(
            server for adapter in connected for server in adapter.dns_servers
        ))
        addresses = [address for adapter in connected for address in adapter.ipv4]
        apipa = []
        valid = False
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            if isinstance(parsed, ipaddress.IPv4Address) and parsed in ipaddress.ip_network(
                "169.254.0.0/16"
            ):
                apipa.append(address)
            elif (
                isinstance(parsed, ipaddress.IPv4Address)
                and not parsed.is_unspecified
                and not parsed.is_loopback
                and not parsed.is_multicast
            ):
                valid = True
        return NetworkConfiguration(
            hostname=socket.gethostname(),
            adapters=adapters,
            default_gateway=gateway,
            dns_servers=dns_servers,
            apipa_addresses=apipa,
            valid_ipv4=valid,
        )

    def ping(self, destination, count=None, timeout_ms=None):
        count = count or NETWORK_THRESHOLDS["ping_count"]
        timeout_ms = timeout_ms or NETWORK_THRESHOLDS["ping_timeout_ms"]
        destination = _validate_destination(destination)
        samples = []
        received = 0
        sent = 0
        error = None
        for _ in range(count):
            result = self._run(
                ["ping", "-n", "1", "-w", str(timeout_ms), destination],
                timeout=max(3, timeout_ms / 1000 + 2),
            )
            if result.get("return_code") is None:
                error = result.get("error") or "No fue posible ejecutar ping."
                continue
            sent += 1
            text = result.get("stdout", "") + "\n" + result.get("stderr", "")
            if result["return_code"] == 0:
                received += 1
                latency = _parse_ping_latency(text)
                if latency is not None:
                    samples.append(latency)
        lost = max(0, sent - received)
        loss = round(lost * 100 / sent, 1) if sent else 0
        result = PingResult(
            destination=destination,
            packets_sent=sent,
            packets_received=received,
            packets_lost=lost,
            packet_loss_percent=loss,
            minimum_ms=min(samples) if samples else None,
            maximum_ms=max(samples) if samples else None,
            average_ms=round(sum(samples) / len(samples), 2) if samples else None,
            samples_ms=samples,
            error=error,
        )
        result.findings = _ping_findings(result, "RED")
        return result

    def gateway_test(self, configuration=None):
        configuration = configuration or self.get_configuration()
        address = configuration.default_gateway
        if not address:
            return GatewayResult(address=None, reachable=None)
        ping = self.ping(address)
        return GatewayResult(
            address=address,
            reachable=(
                None if ping.packets_sent == 0
                else ping.packets_received > 0
            ),
            ping=ping,
        )

    def dns_test(self, domain=DIAGNOSTIC_DOMAINS[0], servers=None):
        configuration = self.get_configuration() if servers is None else None
        servers = list(dict.fromkeys(
            servers if servers is not None else configuration.dns_servers
        ))
        resolved = []
        resolution_succeeded = False
        error = None
        try:
            records = self._resolver(domain, None, type=socket.SOCK_STREAM)
            resolved = list(dict.fromkeys(item[4][0] for item in records))
            resolution_succeeded = bool(resolved)
        except (OSError, socket.gaierror) as exception:
            error = str(exception)
            logger.info("Resolución DNS fallida | dominio=%s", domain)

        responses = {}
        for server in servers:
            try:
                responses[server] = self._dns_server_query(server, domain)
            except (OSError, ValueError, struct.error):
                logger.warning(
                    "No se pudo comprobar DNS en el servidor configurado %s",
                    server,
                    exc_info=True,
                )
                responses[server] = False
        return DnsResult(
            configured_servers=servers,
            domain=domain,
            resolution_succeeded=resolution_succeeded,
            resolved_addresses=resolved,
            server_responses=responses,
            error=error,
        )

    @staticmethod
    def _dns_server_query(server, domain):
        query_id = int(time.time_ns()) & 0xFFFF
        labels = domain.rstrip(".").split(".")
        encoded_name = b"".join(
            bytes((len(label.encode("idna")),)) + label.encode("idna")
            for label in labels
        ) + b"\0"
        question = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
        question += encoded_name + struct.pack("!HH", 1, 1)
        family = socket.AF_INET6 if ":" in server else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as connection:
            connection.settimeout(NETWORK_THRESHOLDS["dns_timeout_seconds"])
            connection.sendto(question, (server, 53))
            response, _ = connection.recvfrom(4096)
        if len(response) < 12:
            return False
        response_id, flags, _questions, _answers, _authority, _additional = (
            struct.unpack("!HHHHHH", response[:12])
        )
        if response_id != query_id or not flags & 0x8000:
            return False
        return True

    def internet_test(self):
        for host, port in EXTERNAL_PROBES:
            try:
                with socket.create_connection((host, port), timeout=2.5):
                    return {"reachable": True, "probe": f"{host}:{port}", "error": None}
            except OSError as error:
                logger.info(
                    "Prueba externa fallida | destino=%s:%s | error=%s",
                    host,
                    port,
                    error,
                )
        return {
            "reachable": False,
            "probe": ", ".join(f"{host}:{port}" for host, port in EXTERNAL_PROBES),
            "error": "No respondieron las pruebas TCP externas configuradas.",
        }

    def traceroute(self, destination, max_hops=None, timeout_ms=None):
        destination = _validate_destination(destination)
        max_hops = max_hops or NETWORK_THRESHOLDS["traceroute_max_hops"]
        timeout_ms = timeout_ms or NETWORK_THRESHOLDS["traceroute_timeout_ms"]
        result = self._run(
            [
                "tracert",
                "-d",
                "-h",
                str(max_hops),
                "-w",
                str(timeout_ms),
                destination,
            ],
            timeout=max_hops * timeout_ms / 1000 + 5,
        )
        hops = []
        for line in result.get("stdout", "").splitlines():
            match = re.match(r"^\s*(\d+)\s+(.*)$", line)
            if not match:
                continue
            route = match.group(2).strip()
            if route.count("*") >= 3:
                route = "* * *"
            hops.append(
                {
                    "hop": int(match.group(1)),
                    "route": route or "* * *",
                    "responded": route != "* * *",
                }
            )
        return {
            "destination": destination,
            "hops": hops,
            "completed": result.get("return_code") == 0,
            "error": result.get("error"),
            "source": "tracert",
            "timestamp": _timestamp(),
        }

    def renew_ip_configuration(self):
        commands = ["ipconfig /release", "ipconfig /renew"]
        outputs = []
        release = self._run(["ipconfig", "/release"], timeout=30)
        outputs.append(_action_output("ipconfig /release", release))
        if release.get("return_code") == 0:
            renew = self._run(["ipconfig", "/renew"], timeout=60)
            outputs.append(_action_output("ipconfig /renew", renew))
        success = (
            len(outputs) == len(commands)
            and all(item["return_code"] == 0 for item in outputs)
        )
        result = NetworkActionResult(
            action="renovar configuración IP",
            success=success,
            commands=commands[:len(outputs)],
            outputs=outputs,
            user=getpass.getuser(),
        )
        logger.info(
            "Acción de red | usuario=%s | acción=%s | resultado=%s",
            result.user,
            result.action,
            "correcto" if success else "falló",
        )
        if not success:
            logger.error(
                "Renovación IP falló | comandos=%s",
                [
                    (item["command"], item["return_code"], item["error"])
                    for item in outputs
                ],
            )
        return result

    def reset_network(self):
        commands = [
            ["netsh", "winsock", "reset"],
            ["netsh", "int", "ip", "reset"],
        ]
        outputs = []
        for command in commands:
            result = self._run(command, timeout=30)
            outputs.append(_action_output(" ".join(command), result))
            if result.get("return_code") != 0:
                break
        success = (
            len(outputs) == len(commands)
            and all(item["return_code"] == 0 for item in outputs)
        )
        result = NetworkActionResult(
            action="restablecer configuración de red",
            success=success,
            commands=[item["command"] for item in outputs],
            outputs=outputs,
            user=getpass.getuser(),
            requires_restart=any(
                item["return_code"] == 0 for item in outputs
            ),
        )
        logger.info(
            "Acción de red profesional | usuario=%s | acción=%s | resultado=%s",
            result.user,
            result.action,
            "correcto" if success else "falló",
        )
        if not success:
            logger.error(
                "Restablecimiento de red falló | comandos=%s",
                [
                    (item["command"], item["return_code"], item["error"])
                    for item in outputs
                ],
            )
        return result

    def automatic_diagnostic(self):
        logger.info("Diagnóstico automático de red iniciado")
        configuration = self.get_configuration()
        adapters = configuration.adapters
        connected = [
            adapter for adapter in adapters
            if adapter.is_up and adapter.is_physical is not False
            and _is_network_adapter(adapter)
        ]
        valid_ip = configuration.valid_ipv4
        has_apipa = bool(configuration.apipa_addresses)

        gateway = GatewayResult(address=configuration.default_gateway, reachable=None)
        if connected and valid_ip and gateway.address:
            gateway = self.gateway_test(configuration)

        dns = DnsResult(
            configured_servers=configuration.dns_servers,
            domain=DIAGNOSTIC_DOMAINS[0],
            resolution_succeeded=None,
        )
        if connected and valid_ip and (gateway.reachable is not False):
            dns = self.dns_test(servers=configuration.dns_servers)

        internet = {"reachable": None, "probe": None, "error": None}
        if connected and valid_ip and gateway.reachable is not False:
            internet = self.internet_test()

        ping = None
        if gateway.address and connected and valid_ip:
            ping = gateway.ping

        checks = [
            NetworkCheck(
                "Adaptador",
                bool(connected),
                Severity.NORMAL if connected else Severity.ALERT,
                {"connected_adapters": [adapter.name for adapter in connected]},
                "Al menos un adaptador aparece conectado."
                if connected else "No se encontró un adaptador conectado.",
            ),
            NetworkCheck(
                "Configuración IP",
                valid_ip,
                Severity.NORMAL if valid_ip else Severity.ALERT,
                {
                    "ipv4": [
                        address for adapter in connected for address in adapter.ipv4
                    ],
                    "apipa_addresses": configuration.apipa_addresses,
                    "dhcp_enabled": [
                        adapter.dhcp_enabled for adapter in connected
                    ],
                },
                "Se encontró una dirección IPv4 utilizable."
                if valid_ip else (
                    "Se detectó una dirección APIPA; podría haber un problema de asignación DHCP."
                    if has_apipa else "No se obtuvo una dirección IPv4 utilizable."
                ),
            ),
            NetworkCheck(
                "Gateway",
                gateway.reachable,
                Severity.NORMAL if gateway.reachable else (
                    Severity.ALERT if gateway.reachable is False else Severity.INFORMATION
                ),
                {"address": gateway.address},
                "Gateway responde a ping."
                if gateway.reachable else "Gateway no accesible o prueba no disponible.",
            ),
            NetworkCheck(
                "DNS",
                dns.resolution_succeeded,
                Severity.NORMAL if dns.resolution_succeeded else (
                    Severity.ALERT
                    if dns.resolution_succeeded is False and internet["reachable"]
                    else Severity.INFORMATION
                    if dns.resolution_succeeded is None
                    else Severity.ALERT
                ),
                {
                    "servers": dns.configured_servers,
                    "domain": dns.domain,
                    "resolved_addresses": dns.resolved_addresses,
                    "server_responses": dns.server_responses,
                },
                "La resolución de dominio respondió."
                if dns.resolution_succeeded else "No fue posible resolver el dominio probado.",
            ),
            NetworkCheck(
                "Internet",
                internet["reachable"],
                Severity.NORMAL if internet["reachable"] else (
                    Severity.ALERT
                    if internet["reachable"] is False and dns.resolution_succeeded
                    else Severity.INFORMATION
                    if internet["reachable"] is None
                    else Severity.ALERT
                ),
                {"probe": internet["probe"]},
                "Se estableció conexión TCP a un destino externo."
                if internet["reachable"] else "No se confirmó conectividad externa.",
            ),
        ]
        if ping:
            latency_ok = (
                None if ping.average_ms is None
                else ping.average_ms < NETWORK_THRESHOLDS["latency_alert_ms"]
            )
            loss_ok = (
                None if ping.packets_sent == 0
                else ping.packet_loss_percent
                < NETWORK_THRESHOLDS["packet_loss_alert_percent"]
            )
            checks.extend(
                (
                    NetworkCheck(
                        "Latencia",
                        latency_ok,
                        Severity.NORMAL if latency_ok else (
                            Severity.ALERT if latency_ok is False
                            else Severity.INFORMATION
                        ),
                        {
                            "destination": ping.destination,
                            "average_ms": ping.average_ms,
                            "threshold_ms": NETWORK_THRESHOLDS["latency_alert_ms"],
                        },
                        "Latencia promedio dentro del umbral."
                        if latency_ok else "Latencia elevada o no disponible.",
                    ),
                    NetworkCheck(
                        "Pérdida de paquetes",
                        loss_ok,
                        Severity.NORMAL if loss_ok else (
                            Severity.ALERT if loss_ok is False
                            else Severity.INFORMATION
                        ),
                        {
                            "destination": ping.destination,
                            "loss_percent": ping.packet_loss_percent,
                            "threshold_percent": NETWORK_THRESHOLDS[
                                "packet_loss_alert_percent"
                            ],
                        },
                        "Pérdida de paquetes dentro del umbral."
                        if loss_ok else "Pérdida de paquetes elevada o no disponible.",
                    ),
                )
            )
        ping = gateway.ping if gateway else None
        findings = self._network_findings(
            connected, configuration, gateway, dns, internet
        )
        if ping:
            findings.extend(_ping_findings(ping, "GATEWAY"))
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
        diagnosis, recommendation = _interpret_network(
            connected, configuration, gateway, dns, internet, ping
        )
        result = NetworkDiagnosticResult(
            timestamp=_timestamp(),
            adapters=adapters,
            configuration=configuration,
            gateway=gateway,
            dns=dns,
            internet_reachable=internet["reachable"],
            internet_probe=internet["probe"],
            ping=ping,
            traceroute=None,
            checks=checks,
            findings=findings,
            severity=severity,
            diagnosis=diagnosis,
            recommendation=recommendation,
        )
        logger.info(
            "Diagnóstico automático de red finalizado | estado=%s | hallazgos=%s",
            result.severity.label,
            len(result.findings),
        )
        return result

    @staticmethod
    def _network_findings(connected, configuration, gateway, dns, internet):
        findings = []
        if not connected:
            findings.append(_finding(
                "NETWORK_ADAPTER_DISCONNECTED", "ADAPTADOR",
                "No hay un adaptador de red conectado", Severity.ALERT,
                "No se detectó ninguna interfaz activa en este equipo.",
                {"adapters": [asdict(adapter) for adapter in configuration.adapters]},
                "desconectado", "conectado",
                "Conectar Wi-Fi o Ethernet y comprobar que el adaptador esté habilitado.",
                "psutil/PowerShell",
            ))
            return findings
        if not configuration.valid_ipv4:
            code = "NETWORK_APIPA_ADDRESS" if configuration.apipa_addresses else "NETWORK_NO_VALID_IP"
            findings.append(_finding(
                code, "CONFIGURACIÓN IP", "No se obtuvo una IPv4 utilizable",
                Severity.ALERT,
                "La interfaz activa no tiene una IPv4 utilizable."
                if not configuration.apipa_addresses
                else "Se detectó una dirección APIPA; puede existir un problema de asignación DHCP.",
                {
                    "apipa_addresses": configuration.apipa_addresses,
                    "addresses": [address for adapter in connected for address in adapter.ipv4],
                    "dhcp_enabled": [adapter.dhcp_enabled for adapter in connected],
                },
                configuration.apipa_addresses or None,
                "IPv4 asignada por red",
                "Comprobar el servidor DHCP y la configuración IP. La APIPA no confirma por sí sola una falla DHCP.",
                "PowerShell/psutil",
            ))
            return findings
        if gateway.address is None:
            findings.append(_finding(
                "NETWORK_GATEWAY_MISSING", "GATEWAY",
                "No hay gateway predeterminado configurado", Severity.ALERT,
                "Windows no reportó una ruta IPv4 predeterminada.",
                {"gateways": [adapter.gateways for adapter in connected]},
                None, "Gateway predeterminado",
                "Revisar la configuración de red y la asignación del gateway.",
                "PowerShell",
            ))
            return findings
        if gateway.reachable is False:
            findings.append(_finding(
                "NETWORK_GATEWAY_UNREACHABLE", "GATEWAY",
                "Gateway no respondió al ping", Severity.ALERT,
                "El equipo tiene una IPv4 y gateway configurados, pero no hubo respuesta ICMP.",
                {
                    "gateway": gateway.address,
                    "ping": asdict(gateway.ping) if gateway.ping else None,
                },
                gateway.address, "Debe responder al menos un ping",
                "Comprobar asociación Wi-Fi/cableado y el estado del router. Algunos gateways filtran ICMP.",
                "ping/PowerShell",
            ))
            return findings
        if dns.resolution_succeeded is False:
            findings.append(_finding(
                "NETWORK_DNS_FAILURE", "DNS",
                "No fue posible resolver nombres de dominio", Severity.ALERT,
                "La prueba de resolución DNS falló. Esto es un indicio y no confirma por sí solo una causa.",
                {
                    "configured_servers": dns.configured_servers,
                    "domain": dns.domain,
                    "server_responses": dns.server_responses,
                    "internet_reachable": internet["reachable"],
                },
                False, True,
                "Revisar la configuración DNS y la conectividad con los servidores configurados.",
                "socket.getaddrinfo / DNS UDP",
            ))
        elif dns.resolution_succeeded is True and internet["reachable"] is False:
            findings.append(_finding(
                "NETWORK_NO_INTERNET", "INTERNET",
                "No se confirmó conectividad externa", Severity.ALERT,
                "Gateway y resolución DNS funcionan, pero no respondieron los destinos TCP externos probados.",
                {
                    "probe": internet["probe"],
                    "dns_domain": dns.domain,
                    "dns_resolved_addresses": dns.resolved_addresses,
                },
                False, True,
                "Comprobar el acceso a Internet del router y si la red filtra conexiones externas.",
                "socket TCP / DNS",
            ))
        elif dns.resolution_succeeded is True and internet["reachable"] is True:
            findings.append(_finding(
                "NETWORK_CONNECTIVITY_NORMAL", "RED",
                "Conectividad de red normal", Severity.NORMAL,
                "La interfaz, configuración IPv4, gateway, DNS y al menos un destino externo respondieron.",
                {
                    "gateway": gateway.address,
                    "dns_servers": dns.configured_servers,
                    "domain": dns.domain,
                    "external_probe": internet["probe"],
                },
                True, True, confidence="ALTA",
                source="psutil/PowerShell/ping/DNS/TCP",
            ))
        else:
            findings.append(_finding(
                "NETWORK_DIAGNOSTIC_INCOMPLETE", "RED",
                "Diagnóstico de conectividad incompleto", Severity.INFORMATION,
                "No se pudo confirmar toda la cadena de conectividad con los proveedores disponibles.",
                {
                    "gateway_reachable": gateway.reachable,
                    "dns_resolution": dns.resolution_succeeded,
                    "internet_reachable": internet["reachable"],
                },
                confidence="BAJA",
                source="psutil/PowerShell/DNS/TCP",
            ))
        return findings


def _interpret_network(connected, configuration, gateway, dns, internet, ping=None):
    if not connected:
        return (
            "ADAPTADOR DESCONECTADO",
            "Conectar Wi-Fi o Ethernet y comprobar que el adaptador esté habilitado.",
        )
    if not configuration.valid_ipv4:
        if configuration.apipa_addresses:
            return (
                "POSIBLE PROBLEMA DE ASIGNACIÓN IP/DHCP",
                "Comprobar el servidor DHCP. Una dirección APIPA es un indicio, no prueba definitiva.",
            )
        return (
            "PROBLEMA DE CONFIGURACIÓN IP",
            "Comprobar que la interfaz haya recibido una IPv4 válida.",
        )
    if not gateway.address:
        return (
            "GATEWAY NO CONFIGURADO",
            "Revisar las rutas y la configuración de red.",
        )
    if gateway.reachable is False:
        return (
            "POSIBLE PROBLEMA DE CONECTIVIDAD LOCAL",
            "Comprobar el enlace local y el gateway. La política ICMP del router puede afectar el resultado.",
        )
    if dns.resolution_succeeded is False and internet["reachable"] is True:
        return (
            "POSIBLE PROBLEMA DNS",
            "Revisar la configuración DNS o la conectividad con el servidor configurado.",
        )
    if dns.resolution_succeeded is False:
        return (
            "POSIBLE PROBLEMA DE RESOLUCIÓN DNS",
            "Revisar los servidores DNS configurados; tampoco se confirmó conectividad externa.",
        )
    if dns.resolution_succeeded is True and internet["reachable"] is False:
        return (
            "POSIBLE PROBLEMA DE CONECTIVIDAD EXTERNA",
            "Comprobar el acceso a Internet y si la red filtra los destinos probados.",
        )
    if dns.resolution_succeeded is True and internet["reachable"] is True:
        if ping and ping.packet_loss_percent >= NETWORK_THRESHOLDS["packet_loss_alert_percent"]:
            return (
                "CONECTIVIDAD CON PÉRDIDA DE PAQUETES",
                "Se observó pérdida al gateway probado; repetir y comparar con otros destinos antes de atribuir la causa.",
            )
        if ping and ping.average_ms is not None and ping.average_ms >= NETWORK_THRESHOLDS["latency_alert_ms"]:
            return (
                "CONECTIVIDAD CON LATENCIA ELEVADA",
                "La latencia media al gateway superó el umbral; repetir la prueba antes de atribuir la causa.",
            )
        return (
            "CONECTIVIDAD NORMAL",
            "No se requiere una acción inmediata.",
        )
    return (
        "RESULTADO INDETERMINADO",
        "Repetir la prueba y revisar cualquier dato que aparezca como no disponible.",
    )


def _ping_findings(ping, component):
    findings = []
    if ping.packets_sent and (
        ping.packet_loss_percent
        >= NETWORK_THRESHOLDS["packet_loss_alert_percent"]
    ):
        findings.append(
            _finding(
                "NETWORK_HIGH_PACKET_LOSS",
                component,
                "Pérdida de paquetes detectada",
                Severity.ALERT,
                "La prueba reportó pérdida de paquetes al destino probado; esto no identifica por sí solo la causa.",
                {
                    "destination": ping.destination,
                    "packets_sent": ping.packets_sent,
                    "packets_received": ping.packets_received,
                    "packets_lost": ping.packets_lost,
                    "packet_loss_percent": ping.packet_loss_percent,
                },
                ping.packet_loss_percent,
                f"< {NETWORK_THRESHOLDS['packet_loss_alert_percent']:g}%",
                "Repetir la prueba y comparar con gateway y otro destino antes de revisar el adaptador.",
                "ping",
            )
        )
    if (
        ping.average_ms is not None
        and ping.average_ms >= NETWORK_THRESHOLDS["latency_alert_ms"]
    ):
        findings.append(
            _finding(
                "NETWORK_HIGH_LATENCY",
                component,
                "Latencia elevada detectada",
                Severity.ALERT,
                "La latencia promedio al destino probado superó el umbral configurado.",
                {
                    "destination": ping.destination,
                    "minimum_ms": ping.minimum_ms,
                    "maximum_ms": ping.maximum_ms,
                    "average_ms": ping.average_ms,
                },
                ping.average_ms,
                f"< {NETWORK_THRESHOLDS['latency_alert_ms']:g} ms",
                "Repetir la medición y comparar latencia hacia el gateway y un destino externo.",
                "ping",
            )
        )
    return findings


def _finding(code, component, title, severity, description, evidence,
             current_value=None, expected_value=None, recommendation="",
             source="PowerShell / psutil", confidence=None):
    logger.info(
        "Hallazgo de red generado | codigo=%s | severidad=%s",
        code,
        severity.label,
    )
    return DiagnosticResult(
        code=code,
        component=component,
        title=title,
        severity=severity,
        description=description,
        evidence=evidence,
        current_value=current_value,
        expected_value=expected_value,
        recommendation=recommendation,
        confidence=confidence or (
            "MEDIA" if severity != Severity.NORMAL else "ALTA"
        ),
        source=source,
        rule_id=code,
    )


def _list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_speed(value):
    if not value:
        return None
    text = str(value).strip().upper().replace(",", ".")
    match = re.search(r"([\d.]+)\s*(GBPS|MBPS|KBPS)", text)
    if match:
        number = float(match.group(1))
        unit = match.group(2)
        return number * 1000 if unit == "GBPS" else number / 1000 if unit == "KBPS" else number
    return None


def _adapter_type(name, description, status):
    details = f"{name} {description}".casefold()
    if any(token in details for token in ("wi-fi", "wifi", "wireless", "802.11")):
        return "Wi-Fi"
    if "ethernet" in details or "gigabit" in details:
        return "Ethernet"
    if "bluetooth" in details:
        return "Bluetooth"
    return "Red cableada" if status else "No disponible"


def _is_network_adapter(adapter):
    identity = f"{adapter.name} {adapter.description or ''}".casefold()
    excluded = (
        "loopback", "virtual", "vpn", "tunnel", "docker",
        "hyper-v", "vmware", "virtualbox", "bluetooth",
    )
    return not any(token in identity for token in excluded)


def _parse_ping_latency(output):
    match = re.search(
        r"(?:time|tiempo)\s*[=<]\s*(\d+)\s*ms",
        output,
        re.IGNORECASE,
    )
    if match:
        return float(match.group(1))
    match = re.search(r"\btime[=<]\s*(\d+)\s*ms", output, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _validate_destination(destination):
    value = str(destination or "").strip()
    if not value or len(value) > 253 or any(char in value for char in "\r\n\x00"):
        raise ValueError("Destino de red vacío o no válido.")
    if not re.fullmatch(r"[A-Za-z0-9._:%-]+", value):
        raise ValueError("Usa un nombre de host o una dirección IP válida.")
    return value


def _action_output(command, result):
    return {
        "command": command,
        "return_code": result.get("return_code"),
        "stdout": result.get("stdout", "")[-2000:],
        "stderr": result.get("stderr", "")[-1000:],
        "error": result.get("error"),
    }
