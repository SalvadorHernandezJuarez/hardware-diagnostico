import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from core.severity import Severity
from modules.red import (
    NETWORK_THRESHOLDS,
    DnsResult,
    GatewayResult,
    NetworkAdapter,
    NetworkConfiguration,
    NetworkDiagnostics,
    PingResult,
)
from ui.red import NetworkMenu


def _configuration(address="192.168.1.10", gateway="192.168.1.1"):
    adapter = NetworkAdapter(
        name="Wi-Fi",
        description="Wireless adapter",
        status="Conectado",
        adapter_type="Wi-Fi",
        ipv4=[address],
        gateways=[gateway] if gateway else [],
        dns_servers=["192.168.1.1"],
        dhcp_enabled=True,
        is_up=True,
        is_physical=True,
    )
    apipa = [address] if address.startswith("169.254.") else []
    return NetworkConfiguration(
        hostname="test-host",
        adapters=[adapter],
        default_gateway=gateway,
        dns_servers=["192.168.1.1"],
        apipa_addresses=apipa,
        valid_ipv4=not apipa,
    )


class FakeNetwork(NetworkDiagnostics):
    def __init__(self, configuration, gateway, dns, internet):
        super().__init__()
        self.configuration = configuration
        self.gateway_result = gateway
        self.dns_result = dns
        self.internet_result = internet
        self.dns_calls = 0
        self.internet_calls = 0

    def get_configuration(self):
        return self.configuration

    def gateway_test(self, configuration=None):
        return self.gateway_result

    def dns_test(self, domain=None, servers=None):
        self.dns_calls += 1
        return self.dns_result

    def internet_test(self):
        self.internet_calls += 1
        return self.internet_result


class NetworkDiagnosticsTests(unittest.TestCase):
    def test_apipa_is_detected_as_possible_dhcp_issue_not_confirmed_cause(self):
        rows = [
            {
                "Name": "Wi-Fi",
                "InterfaceIndex": 11,
                "Description": "Wireless adapter",
                "Status": "Up",
                "Physical": True,
                "IPv4": ["169.254.2.3"],
                "Gateway": [],
                "DNS": [],
                "DhcpEnabled": "Enabled",
            }
        ]
        addresses = {
            "Wi-Fi": [
                Mock(family=2, address="169.254.2.3", netmask="255.255.0.0"),
                Mock(family=Mock(), address="00-11-22-33-44-55"),
            ]
        }
        stats = {"Wi-Fi": Mock(isup=True, speed=300)}
        with (
            patch("modules.red.psutil.net_if_addrs", return_value=addresses),
            patch("modules.red.psutil.net_if_stats", return_value=stats),
            patch.object(NetworkDiagnostics, "_wifi_details", return_value={}),
        ):
            network = NetworkDiagnostics(powershell_query=lambda _script: rows)
            configuration = network.get_configuration()

        self.assertEqual(configuration.apipa_addresses, ["169.254.2.3"])
        self.assertFalse(configuration.valid_ipv4)

    def test_gateway_failure_stops_dns_and_external_probes(self):
        gateway = GatewayResult("192.168.1.1", False)
        dns = DnsResult(["192.168.1.1"], "example.com", False)
        network = FakeNetwork(
            _configuration(), gateway, dns,
            {"reachable": False, "probe": "external", "error": "timeout"},
        )
        result = network.automatic_diagnostic()

        self.assertEqual(network.dns_calls, 0)
        self.assertEqual(network.internet_calls, 0)
        self.assertEqual(result.findings[0].code, "NETWORK_GATEWAY_UNREACHABLE")
        self.assertEqual(
            result.diagnosis,
            "POSIBLE PROBLEMA DE CONECTIVIDAD LOCAL",
        )

    def test_apipa_stops_gateway_dns_and_internet_probes(self):
        network = FakeNetwork(
            _configuration("169.254.2.3", None),
            GatewayResult(None, None),
            DnsResult([], "example.com", None),
            {"reachable": None, "probe": None, "error": None},
        )
        result = network.automatic_diagnostic()

        self.assertEqual(network.dns_calls, 0)
        self.assertEqual(network.internet_calls, 0)
        self.assertEqual(result.findings[0].code, "NETWORK_APIPA_ADDRESS")
        self.assertIn("POSIBLE PROBLEMA", result.diagnosis)

    def test_dns_failure_with_external_connectivity_is_diagnosed_as_possible_dns(self):
        network = FakeNetwork(
            _configuration(),
            GatewayResult("192.168.1.1", True),
            DnsResult(
                ["192.168.1.1"], "example.com", False,
                server_responses={"192.168.1.1": False},
            ),
            {"reachable": True, "probe": "1.1.1.1:443", "error": None},
        )
        result = network.automatic_diagnostic()

        self.assertEqual(result.diagnosis, "POSIBLE PROBLEMA DNS")
        finding = next(item for item in result.findings if item.code == "NETWORK_DNS_FAILURE")
        self.assertEqual(finding.severity, Severity.ALERT)
        self.assertEqual(finding.current_value, False)

    def test_connected_dns_and_internet_yield_normal_connectivity(self):
        network = FakeNetwork(
            _configuration(),
            GatewayResult("192.168.1.1", True),
            DnsResult(["192.168.1.1"], "example.com", True, ["93.184.216.34"]),
            {"reachable": True, "probe": "1.1.1.1:443", "error": None},
        )
        result = network.automatic_diagnostic()

        self.assertEqual(result.diagnosis, "CONECTIVIDAD NORMAL")
        self.assertEqual(result.severity, Severity.NORMAL)
        self.assertEqual(result.findings[0].code, "NETWORK_CONNECTIVITY_NORMAL")
        self.assertEqual(
            [check.name for check in result.checks],
            ["Adaptador", "Configuración IP", "Gateway", "DNS", "Internet"],
        )
        self.assertIn("commands", result.to_dict())
        self.assertIn("NORMAL", json.dumps(result.to_dict(), ensure_ascii=False))

    def test_powershell_adapter_status_overrides_stale_psutil_link_state(self):
        rows = [
            {
                "Name": "Wi-Fi",
                "InterfaceIndex": 11,
                "Description": "Wireless adapter",
                "Status": "Disconnected",
                "Physical": True,
                "IPv4": [],
                "Gateway": [],
                "DNS": [],
            }
        ]
        with (
            patch("modules.red.psutil.net_if_addrs", return_value={}),
            patch(
                "modules.red.psutil.net_if_stats",
                return_value={"Wi-Fi": Mock(isup=True, speed=300)},
            ),
            patch.object(NetworkDiagnostics, "_wifi_details", return_value={}),
        ):
            adapters = NetworkDiagnostics(
                powershell_query=lambda _script: rows
            ).get_adapters()

        self.assertFalse(adapters[0].is_up)
        self.assertEqual(adapters[0].status, "Desconectado")

    def test_ping_aggregates_received_loss_and_latency_across_attempts(self):
        responses = [
            {"return_code": 0, "stdout": "Reply from 8.8.8.8: time=10ms TTL=55"},
            {"return_code": 1, "stdout": "Request timed out."},
            {"return_code": 0, "stdout": "Reply from 8.8.8.8: time=20ms TTL=55"},
            {"return_code": 0, "stdout": "Respuesta desde 8.8.8.8: tiempo=15ms TTL=55"},
        ]
        network = NetworkDiagnostics(command_runner=Mock(side_effect=responses))

        result = network.ping("8.8.8.8", count=4)

        self.assertEqual(result.packets_sent, 4)
        self.assertEqual(result.packets_received, 3)
        self.assertEqual(result.packets_lost, 1)
        self.assertEqual(result.packet_loss_percent, 25)
        self.assertEqual(result.minimum_ms, 10)
        self.assertEqual(result.maximum_ms, 20)
        self.assertEqual(result.average_ms, 15)
        self.assertEqual(result.findings[0].code, "NETWORK_HIGH_PACKET_LOSS")
        self.assertEqual(result.findings[0].severity, Severity.ALERT)

    def test_ping_command_uses_argument_list_and_rejects_shell_metacharacters(self):
        command = Mock(return_value={"return_code": 0, "stdout": "time=1ms"})
        network = NetworkDiagnostics(command_runner=command)
        network.ping("example.com", count=1)
        self.assertEqual(command.call_args.args[0][:3], ["ping", "-n", "1"])
        with self.assertRaises(ValueError):
            network.ping("example.com & whoami")
        self.assertEqual(command.call_count, 1)

    def test_unavailable_ping_is_not_counted_as_packet_loss_or_gateway_failure(self):
        network = NetworkDiagnostics(
            command_runner=Mock(
                return_value={
                    "return_code": None,
                    "stdout": "",
                    "stderr": "",
                    "error": "ping command unavailable",
                }
            )
        )
        ping = network.ping("192.168.1.1", count=2)
        gateway = network.gateway_test(_configuration())

        self.assertEqual(ping.packets_sent, 0)
        self.assertEqual(ping.packets_lost, 0)
        self.assertEqual(ping.packet_loss_percent, 0)
        self.assertIsNone(gateway.reachable)

    def test_traceroute_timeout_hops_remain_neutral(self):
        runner = Mock(
            return_value={
                "return_code": 0,
                "stdout": (
                    "Tracing route to example.com\n"
                    "  1    2 ms    3 ms    2 ms  192.168.1.1\n"
                    "  2    *        *        *     Request timed out.\n"
                    "Trace complete."
                ),
                "error": None,
            }
        )
        result = NetworkDiagnostics(command_runner=runner).traceroute("example.com")

        self.assertEqual(result["hops"][1]["route"], "* * *")
        self.assertFalse(result["hops"][1]["responded"])
        self.assertTrue(result["completed"])

    def test_ip_renew_runs_renew_only_after_release_success(self):
        runner = Mock(
            side_effect=[
                {"return_code": 0, "stdout": "released", "stderr": ""},
                {"return_code": 0, "stdout": "renewed", "stderr": ""},
            ]
        )
        result = NetworkDiagnostics(command_runner=runner).renew_ip_configuration()

        self.assertTrue(result.success)
        self.assertEqual(result.commands, ["ipconfig /release", "ipconfig /renew"])
        self.assertEqual(runner.call_count, 2)

    def test_failed_ip_release_does_not_run_renew(self):
        runner = Mock(return_value={"return_code": 1, "stderr": "failed"})
        result = NetworkDiagnostics(command_runner=runner).renew_ip_configuration()

        self.assertFalse(result.success)
        self.assertEqual(result.commands, ["ipconfig /release"])
        self.assertEqual(runner.call_count, 1)

    def test_network_reset_has_only_expected_native_commands_and_requires_restart(self):
        runner = Mock(
            return_value={"return_code": 0, "stdout": "OK", "stderr": ""}
        )
        result = NetworkDiagnostics(command_runner=runner).reset_network()

        self.assertTrue(result.success)
        self.assertTrue(result.requires_restart)
        self.assertEqual(
            result.commands,
            ["netsh winsock reset", "netsh int ip reset"],
        )

    def test_latency_and_loss_thresholds_are_centralized(self):
        self.assertEqual(NETWORK_THRESHOLDS["latency_alert_ms"], 150)
        self.assertEqual(NETWORK_THRESHOLDS["packet_loss_alert_percent"], 10)

    def test_automatic_diagnostic_reports_latency_and_loss_checks(self):
        ping = PingResult(
            "192.168.1.1",
            packets_sent=4,
            packets_received=3,
            packets_lost=1,
            packet_loss_percent=25,
            minimum_ms=20,
            maximum_ms=240,
            average_ms=160,
        )
        network = FakeNetwork(
            _configuration(),
            GatewayResult("192.168.1.1", True, ping),
            DnsResult(["192.168.1.1"], "example.com", True, ["93.184.216.34"]),
            {"reachable": True, "probe": "1.1.1.1:443", "error": None},
        )
        result = network.automatic_diagnostic()

        checks = {check.name: check for check in result.checks}
        self.assertFalse(checks["Latencia"].status)
        self.assertFalse(checks["Pérdida de paquetes"].status)
        self.assertIn(
            "NETWORK_HIGH_LATENCY",
            [finding.code for finding in result.findings],
        )
        self.assertIn(
            "NETWORK_HIGH_PACKET_LOSS",
            [finding.code for finding in result.findings],
        )


class NetworkMenuTests(unittest.TestCase):
    def test_network_reset_is_hidden_in_normal_menu_and_listed_in_professional(self):
        with patch("builtins.print") as printer:
            NetworkMenu._menu(professional=False)
        normal_output = " ".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertNotIn("Restablecimiento de red", normal_output)

        with patch("builtins.print") as printer:
            NetworkMenu._menu(professional=True)
        professional_output = " ".join(
            str(call.args[0]) for call in printer.call_args_list
        )
        self.assertIn("[10] Restablecimiento de red", professional_output)

    def test_normal_mode_cannot_dispatch_network_reset(self):
        menu = NetworkMenu(Mock())
        with (
            patch("builtins.input", side_effect=["10", "0"]),
            patch("ui.red.NetworkDiagnostics.reset_network") as reset,
            patch("ui.red.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu.mostrar(professional=False)

        reset.assert_not_called()

    def test_ip_renew_requires_explicit_selection(self):
        menu = NetworkMenu(Mock())
        with (
            patch("builtins.input", return_value="0"),
            patch("ui.red.NetworkDiagnostics.renew_ip_configuration") as renew,
            patch("ui.red.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu._renew_ip()

        renew.assert_not_called()

    def test_reset_requires_literal_professional_confirmation(self):
        menu = NetworkMenu(Mock())
        with (
            patch("builtins.input", return_value="confirmar"),
            patch("ui.red.NetworkDiagnostics.reset_network") as reset,
            patch("ui.red.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu._reset_network()

        reset.assert_not_called()

    def test_reset_executes_only_after_exact_professional_confirmation(self):
        menu = NetworkMenu(Mock())
        result = Mock(
            success=False,
            requires_restart=False,
            outputs=[],
        )
        with (
            patch("builtins.input", return_value="CONFIRMAR"),
            patch("ui.red.NetworkDiagnostics.reset_network", return_value=result) as reset,
            patch("ui.red.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu._reset_network()

        reset.assert_called_once()


if __name__ == "__main__":
    unittest.main()
