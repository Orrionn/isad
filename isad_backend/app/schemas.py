"""Схемы данных ИСАД: ответы API и аналитический отчёт.

Схема отчёта согласована с ТЗ:
- FR-46/FR-47 — исходное и нормализованное значения хранятся отдельно;
- FR-48/FR-51/FR-56 — ссылка на подтверждающий фрагмент;
- FR-49/FR-53 — явная пометка неопределённости;
- FR-55 (п. 1) — предупреждение об отсутствии информации может не иметь цитаты;
- FR-57 — несколько подтверждающих фрагментов;
- FR-58/FR-60 — статус проверки источника для фильтрации;
- FR-61/FR-62 — метаданные отчёта и явное указание неполноты.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models import AnalysisStatus


# ---------------------------------------------------------------------------
# Служебные схемы ответов API
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    sha256: str
    created_at: datetime


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    status: AnalysisStatus
    error_message: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Аналитический отчёт
# ---------------------------------------------------------------------------

def _empty_str_to_none(value: object) -> object:
    """Пустая строка -> None.

    Модель может вернуть "" в source_excerpt для предупреждений об отсутствии
    ожидаемой информации (FR-55 п. 1): подтверждающего фрагмента у такого вывода
    не существует. Без этого преобразования Pydantic отклоняет весь отчёт
    ошибкой string_too_short.
    """
    if isinstance(value, str):
        return value.strip() or None
    return value


SourceQuote = Annotated[str | None, BeforeValidator(_empty_str_to_none)]


class SourceValidation(str, Enum):
    """Статус проверки подтверждающего фрагмента (FR-58, FR-60)."""

    confirmed = "confirmed"            # цитата найдена в исходном тексте
    unverified = "unverified"          # цитата не найдена или источник не указан
    not_applicable = "not_applicable"  # источника не может быть (предупреждение об отсутствии)


CLAUSE_CATEGORIES = {
    "PARTIES", "SUBJECT", "TERM", "RENT", "DEPOSIT", "UTILITIES",
    "RIGHTS_OBLIGATIONS", "MAINTENANCE", "TRANSFER", "TERMINATION",
    "LIABILITY", "SUBLEASE", "MISC",
}

_CATEGORY_SYNONYMS = {
    "PAYMENT": "RENT",
    "RENT_PAYMENT": "RENT",
    "SECURITY_DEPOSIT": "DEPOSIT",
    "COMMUNAL": "UTILITIES",
    "UTILITIES_PAYMENT": "UTILITIES",
    "OBLIGATIONS": "RIGHTS_OBLIGATIONS",
    "RIGHTS": "RIGHTS_OBLIGATIONS",
    "RESPONSIBILITY": "LIABILITY",
    "PENALTY": "LIABILITY",
    "EARLY_TERMINATION": "TERMINATION",
    "REPAIR": "MAINTENANCE",
}


class Entity(BaseModel):
    """Извлечённая сущность (FR-45…FR-49)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    value: str | None = None
    normalized_value: str | None = None  # FR-47: не подменяет исходное значение
    source_excerpt: SourceQuote = Field(
        default=None,
        min_length=1,
        description="Подтверждающая цитата из текста договора (FR-48).",
    )
    source_validation: SourceValidation = SourceValidation.unverified
    source_fragments: list[str] = Field(default_factory=list)  # FR-57
    confidence: float | None = Field(default=None, ge=0, le=1)


class Clause(BaseModel):
    """Классифицированное положение договора (FR-50…FR-53)."""

    model_config = ConfigDict(extra="ignore")

    category: str
    summary: str
    source_excerpt: SourceQuote = Field(
        default=None,
        min_length=1,
        description="Фрагмент исходного текста положения (FR-51).",
    )
    source_validation: SourceValidation = SourceValidation.unverified
    source_fragments: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        """Приводит категорию к фиксированной таксономии; неизвестная -> MISC (FR-53)."""
        if isinstance(value, str):
            normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
            normalized = _CATEGORY_SYNONYMS.get(normalized, normalized)
            return normalized if normalized in CLAUSE_CATEGORIES else "MISC"
        return value


class WarningItem(BaseModel):
    """Предупреждение о потенциально проблемном фрагменте (FR-54…FR-60).

    Предупреждение не является юридическим заключением (см. limitations отчёта).
    """

    model_config = ConfigDict(extra="ignore")

    category: str
    severity: str
    description: str
    source_excerpt: SourceQuote = Field(
        default=None,
        min_length=1,
        description=(
            "Подтверждающая цитата. None допускается только для предупреждений "
            "об отсутствии ожидаемой информации (FR-55 п. 1): у такого вывода "
            "цитаты существовать не может (FR-59)."
        ),
    )
    source_validation: SourceValidation = SourceValidation.unverified
    source_fragments: list[str] = Field(default_factory=list)  # FR-57
    recommendation: str | None = None

    @model_validator(mode="after")
    def _sync_source_status(self) -> "WarningItem":
        """Нет цитаты и нет фрагментов -> статус not_applicable (FR-59)."""
        if self.source_excerpt is None and not self.source_fragments:
            self.source_validation = SourceValidation.not_applicable
        return self


class ReportMeta(BaseModel):
    """Метаданные воспроизводимости (FR-40, FR-61 п. 8, раздел 14.4 ТЗ)."""

    pipeline_version: str | None = None
    prompt_version: str | None = None
    model_id: str | None = None
    analyzed_at: datetime | None = None
    is_partial: bool = False  # FR-62: анализ завершён частично


class AnalysisReport(BaseModel):
    summary: str
    entities: list[Entity] = Field(default_factory=list)
    clauses: list[Clause] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Результат является техническим анализом текста, а не юридическим заключением."
        ]
    )
    meta: ReportMeta = Field(default_factory=ReportMeta)