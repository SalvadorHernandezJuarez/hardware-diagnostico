from enum import Enum


class ActionRisk(Enum):
    SAFE = "SEGURA"
    CONFIRMATION = "CONFIRMACIÓN"
    PROFESSIONAL = "PROFESIONAL"

    @property
    def icon(self) -> str:
        return {
            ActionRisk.SAFE: "🟢",
            ActionRisk.CONFIRMATION: "🟡",
            ActionRisk.PROFESSIONAL: "🔴",
        }[self]

    @property
    def display(self) -> str:
        return f"{self.icon} {self.value}"
