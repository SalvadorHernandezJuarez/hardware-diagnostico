from enum import IntEnum


class Severity(IntEnum):
    NORMAL = 0
    INFORMATION = 1
    ALERT = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return {
            Severity.NORMAL: "NORMAL",
            Severity.INFORMATION: "INFORMACIÓN",
            Severity.ALERT: "ALERTA",
            Severity.CRITICAL: "CRÍTICO",
        }[self]

    @property
    def icon(self) -> str:
        return {
            Severity.NORMAL: "✓",
            Severity.INFORMATION: "ℹ",
            Severity.ALERT: "⚠",
            Severity.CRITICAL: "✖",
        }[self]

    @property
    def display(self) -> str:
        return f"{self.icon} {self.label}"
