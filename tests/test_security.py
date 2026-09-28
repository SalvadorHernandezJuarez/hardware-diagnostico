import unittest
from contextlib import redirect_stdout
from io import StringIO
from subprocess import TimeoutExpired
from unittest.mock import Mock, patch

from core.severity import Severity
from modules.security import SECURITY_SECTIONS, SecurityAuditor
from ui.security import SecurityMenu


def _security_data():
    return {
        "firewall": {
            "Available": True,
            "Profiles": [
                {"Name": "Domain", "Enabled": True},
                {"Name": "Private", "Enabled": True},
                {"Name": "Public", "Enabled": True},
            ],
        },
        "defender": {
            "Available": True,
            "Status": {
                "AntivirusEnabled": True,
                "RealTimeProtectionEnabled": True,
                "AntispywareEnabled": True,
                "AntivirusSignatureLastUpdated": "2026-09-27T10:00:00",
            },
            "OtherAntivirus": [],
        },
        "bitlocker": {
            "Available": True,
            "Volumes": [{
                "MountPoint": "C:",
                "VolumeStatus": "FullyEncrypted",
                "EncryptionPercentage": 100,
                "ProtectionStatus": "On",
                "EncryptionMethod": "XtsAes256",
            }],
        },
        "windows_update": {
            "Available": True,
            "OS": {
                "Caption": "Microsoft Windows 11 Pro",
                "Version": "10.0",
                "BuildNumber": "26100",
                "OSArchitecture": "64-bit",
            },
            "PendingAvailable": True,
            "PendingUpdates": [],
            "LastInstalled": "2026-09-01",
        },
        "users": {
            "Available": True,
            "CurrentUser": "PC\\User",
            "CurrentIsAdmin": False,
            "LocalUsers": [{"Name": "User", "Enabled": True}],
            "Administrators": [{"Name": "PC\\Administrator"}],
            "AdministratorsAvailable": True,
        },
        "services": {
            "Available": True,
            "Services": [
                {"Name": "MpsSvc", "DisplayName": "Windows Defender Firewall", "Status": "Running"},
                {"Name": "WinDefend", "DisplayName": "Microsoft Defender Antivirus", "Status": "Running"},
                {"Name": "wuauserv", "DisplayName": "Windows Update", "Status": "Stopped"},
                {"Name": "wscsvc", "DisplayName": "Security Center", "Status": "Running"},
            ],
        },
        "configuration": {
            "Available": True,
            "UACEnabled": True,
            "SecureBoot": True,
            "FirmwareType": "Uefi",
            "TPM": {
                "Present": True,
                "Ready": True,
                "Enabled": True,
                "Activated": True,
            },
        },
    }


class SecurityAuditorTests(unittest.TestCase):
    def audit(self, data=None, sections=None):
        data = _security_data() if data is None else data
        return SecurityAuditor(
            powershell_query=lambda _script: data
        ).audit(sections)

    def test_complete_healthy_audit_produces_normal_structured_result(self):
        result = self.audit()

        self.assertEqual(result.severity, Severity.NORMAL)
        self.assertEqual(set(result.data), set(SECURITY_SECTIONS))
        self.assertIn("SEC_FIREWALL_ENABLED", [item.code for item in result.findings])
        self.assertIn("SEC_DEFENDER_ACTIVE", [item.code for item in result.findings])
        self.assertEqual(result.to_dict()["severity"], "NORMAL")

    def test_disabled_firewall_profile_creates_alert_with_profile_evidence(self):
        data = _security_data()
        data["firewall"]["Profiles"][2]["Enabled"] = False

        result = self.audit(data, ("firewall",))
        finding = next(item for item in result.findings if item.code == "SEC_FIREWALL_DISABLED")

        self.assertEqual(result.severity, Severity.ALERT)
        self.assertEqual(finding.severity, Severity.ALERT)
        self.assertIn("Public", finding.title)

    def test_unknown_firewall_state_is_not_reported_as_enabled(self):
        data = _security_data()
        data["firewall"]["Profiles"][0]["Enabled"] = None

        result = self.audit(data, ("firewall",))

        self.assertIsNone(result.checks[0].status)
        self.assertNotIn("SEC_FIREWALL_ENABLED", [item.code for item in result.findings])
        self.assertFalse(any(item.severity == Severity.ALERT for item in result.findings))

    def test_defender_unavailable_and_registered_other_antivirus_are_not_false_alerts(self):
        data = _security_data()
        data["defender"] = {
            "Available": False,
            "Status": None,
            "OtherAntivirus": [{"DisplayName": "Other antivirus"}],
            "Error": "Managed by another provider",
        }

        result = self.audit(data, ("defender",))

        self.assertEqual(result.severity, Severity.INFORMATION)
        self.assertNotIn("SEC_DEFENDER_DISABLED", [item.code for item in result.findings])
        self.assertIsNone(result.checks[0].status)
        self.assertIn("otro producto antivirus", result.checks[0].description)

    def test_disabled_defender_with_registered_alternative_is_informational(self):
        data = _security_data()
        data["defender"]["Status"]["AntivirusEnabled"] = False
        data["defender"]["OtherAntivirus"] = [{"DisplayName": "Other antivirus"}]

        result = self.audit(data, ("defender",))

        finding = next(item for item in result.findings if item.code == "SEC_DEFENDER_DISABLED")
        self.assertEqual(finding.severity, Severity.INFORMATION)
        self.assertEqual(result.severity, Severity.INFORMATION)

    def test_realtime_protection_off_and_defender_off_use_distinct_findings(self):
        data = _security_data()
        data["defender"]["Status"]["RealTimeProtectionEnabled"] = False

        result = self.audit(data, ("defender",))

        self.assertIn(
            "SEC_REALTIME_PROTECTION_DISABLED",
            [item.code for item in result.findings],
        )
        self.assertEqual(result.severity, Severity.ALERT)

    def test_threat_protection_disabled_creates_a_distinct_alert(self):
        data = _security_data()
        data["defender"]["Status"]["AntispywareEnabled"] = False

        result = self.audit(data, ("defender",))

        self.assertIn(
            "SEC_DEFENDER_THREAT_PROTECTION_DISABLED",
            [item.code for item in result.findings],
        )
        self.assertEqual(result.severity, Severity.ALERT)

    def test_unprotected_bitlocker_volume_is_informational_not_confirmed_vulnerability(self):
        data = _security_data()
        data["bitlocker"]["Volumes"][0].update({
            "VolumeStatus": "FullyDecrypted",
            "EncryptionPercentage": 0,
            "ProtectionStatus": "Off",
        })

        result = self.audit(data, ("bitlocker",))
        finding = next(item for item in result.findings if item.code == "SEC_BITLOCKER_DISABLED")

        self.assertEqual(result.severity, Severity.INFORMATION)
        self.assertEqual(finding.severity, Severity.INFORMATION)

    def test_unknown_bitlocker_protection_state_is_not_called_unprotected(self):
        data = _security_data()
        data["bitlocker"]["Volumes"][0]["ProtectionStatus"] = "Unknown"

        result = self.audit(data, ("bitlocker",))

        self.assertNotIn("SEC_BITLOCKER_DISABLED", [item.code for item in result.findings])
        self.assertIsNone(result.checks[0].status)

    def test_pending_windows_updates_are_reported_without_installing_them(self):
        data = _security_data()
        data["windows_update"]["PendingUpdates"] = [
            {"Title": "Security update", "KBArticleIDs": ["KB123"]}
        ]
        query = Mock(return_value=data)

        result = SecurityAuditor(powershell_query=query).audit(("windows_update",))

        self.assertIn("SEC_UPDATES_PENDING", [item.code for item in result.findings])
        self.assertEqual(result.severity, Severity.ALERT)
        self.assertEqual(query.call_count, 2)
        self.assertIn("Search", query.call_args_list[1].args[0])

    def test_unknown_windows_update_state_is_not_treated_as_current(self):
        data = _security_data()
        del data["windows_update"]["PendingAvailable"]

        result = self.audit(data, ("windows_update",))

        self.assertIn("SEC_UPDATES_UNAVAILABLE", [item.code for item in result.findings])
        self.assertNotIn("SEC_UPDATES_CURRENT", [item.code for item in result.findings])

    def test_user_and_additional_administrators_are_informational(self):
        data = _security_data()
        data["users"]["CurrentIsAdmin"] = True
        data["users"]["Administrators"].append({"Name": "PC\\Support"})

        result = self.audit(data, ("users",))
        codes = [item.code for item in result.findings]

        self.assertIn("SEC_ADMIN_USER", codes)
        self.assertIn("SEC_ADDITIONAL_ADMIN_USERS", codes)
        self.assertEqual(result.severity, Severity.NORMAL)

    def test_uac_and_secure_boot_findings_and_tpm_unavailable(self):
        data = _security_data()
        data["configuration"].update({
            "UACEnabled": False,
            "SecureBoot": False,
            "TPM": {"Present": False, "Ready": False},
        })

        result = self.audit(data, ("configuration",))
        codes = [item.code for item in result.findings]

        self.assertIn("SEC_UAC_DISABLED", codes)
        self.assertIn("SEC_SECURE_BOOT_DISABLED", codes)
        self.assertIn("SEC_TPM_UNAVAILABLE", codes)
        self.assertEqual(result.severity, Severity.ALERT)

    def test_legacy_firmware_does_not_report_secure_boot_disabled(self):
        data = _security_data()
        data["configuration"].update({
            "SecureBoot": False,
            "FirmwareType": "Legacy",
        })

        result = self.audit(data, ("configuration",))

        self.assertNotIn(
            "SEC_SECURE_BOOT_DISABLED",
            [item.code for item in result.findings],
        )

    def test_stopped_demand_started_update_service_is_not_an_alert(self):
        data = _security_data()
        data["services"]["Services"][2]["Status"] = "Stopped"

        result = self.audit(data, ("services",))

        self.assertEqual(result.severity, Severity.NORMAL)
        self.assertFalse(any(item.severity == Severity.ALERT for item in result.findings))

    def test_missing_powershell_data_is_information_not_an_exception(self):
        result = SecurityAuditor(powershell_query=lambda _script: None).audit()

        self.assertEqual(result.severity, Severity.INFORMATION)
        self.assertEqual(len(result.checks), len(SECURITY_SECTIONS))
        self.assertFalse(any(item.severity >= Severity.ALERT for item in result.findings))

    def test_configuration_request_collects_related_settings_together(self):
        query = Mock(return_value=_security_data())

        result = SecurityAuditor(powershell_query=query).audit(("configuration",))

        self.assertEqual(set(result.data), set(SECURITY_SECTIONS))
        script = query.call_args_list[0].args[0]
        self.assertIn("'firewall'", script)
        self.assertIn("'windows_update'", script)

    def test_windows_update_timeout_does_not_discard_other_audit_results(self):
        query = Mock(side_effect=(_security_data(), None))

        result = SecurityAuditor(powershell_query=query).audit()

        self.assertTrue(result.data["firewall"]["available"])
        self.assertFalse(result.data["windows_update"]["pending_available"])
        self.assertIn("SEC_UPDATES_UNAVAILABLE", [item.code for item in result.findings])
        self.assertEqual(query.call_count, 2)

    def test_default_powershell_queries_use_separate_update_timeout(self):
        with patch(
            "modules.security._powershell_json",
            side_effect=(_security_data(), _security_data()),
        ) as query:
            SecurityAuditor().audit()

        self.assertEqual(query.call_args_list[0].kwargs["timeout"], 20)
        self.assertEqual(query.call_args_list[1].kwargs["timeout"], 12)

    def test_powershell_timeout_is_logged_and_reported_as_unavailable(self):
        with (
            patch("modules.security.shutil.which", return_value="powershell.exe"),
            patch(
                "modules.security.subprocess.run",
                side_effect=TimeoutExpired("powershell", timeout=12),
            ),
            self.assertLogs("hardware_diagnostico", level="WARNING"),
        ):
            result = SecurityAuditor().audit(("windows_update",))

        self.assertEqual(result.severity, Severity.INFORMATION)
        self.assertIn("SEC_UPDATES_UNAVAILABLE", [item.code for item in result.findings])

    def test_invalid_section_is_rejected(self):
        with self.assertRaises(ValueError):
            self.audit(sections=("registry",))


class SecurityMenuTests(unittest.TestCase):
    def test_security_menu_shows_all_options(self):
        with redirect_stdout(StringIO()) as output:
            SecurityMenu._show_menu()
        self.assertIn("[8] Auditoría completa", output.getvalue())
        self.assertIn("[0] Volver", output.getvalue())

    def test_complete_audit_is_stored_in_existing_history_logger(self):
        screens = Mock()
        logger = Mock()
        menu = SecurityMenu(screens, logger)
        result = SecurityAuditor(
            powershell_query=lambda _script: _security_data()
        ).audit()
        menu._collect = Mock(return_value=result)

        with (
            patch("ui.security.pausar"),
            redirect_stdout(StringIO()),
        ):
            menu._show_audit(professional=False)

        logger.iniciar_sesion.assert_called_once()
        logger.registrar.assert_called_once()
        self.assertEqual(screens.estado, Severity.NORMAL)
        self.assertIs(menu.last_result, result)


if __name__ == "__main__":
    unittest.main()
