from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict

from core.severity import Severity


@dataclass
class DiagnosticResult:
    code: str
    title: str
    description: str
    evidence: Any = field(default_factory=dict)
    severity: Severity = Severity.INFORMATION
    recommendation: str = ""
    component: str = "SISTEMA"
    current_value: Any = None
    expected_value: Any = None
    confidence: str = "MEDIA"
    timestamp: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )
    source: str = "Desconocida"
    rule_id: str = ""
    priority: int = 100
    possible_causes: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        resultado = asdict(self)
        resultado["severity"] = self.severity.label
        return resultado
