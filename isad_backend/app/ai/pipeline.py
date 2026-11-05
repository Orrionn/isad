import logging
from datetime import datetime, timezone

from app.ai.docx_parser import extract_docx_text, segment_text
from app.ai.llm_client import analyze_chunk, PROMPT_VERSION
from app.config import settings
from app.schemas import AnalysisReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Дедупликация результатов по осмысленным ключам
# (замена слабой `str(item)`-дедупликации)
# ---------------------------------------------------------------------------

def _dedup_entities(items: list[dict]) -> list[dict]:
    """Дедупликация сущностей по (name, value|source_excerpt)."""
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (
            (item.get("name") or "").strip().lower(),
            item.get("normalized_value") or item.get("value") or item.get("source_excerpt") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedup_clauses(items: list[dict]) -> list[dict]:
    """Дедупликация положений по (category, source_excerpt)."""
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (
            (item.get("category") or "").upper(),
            item.get("source_excerpt") or item.get("summary") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedup_warnings(items: list[dict]) -> list[dict]:
    """Дедупликация предупреждений по (category, source_excerpt, description)."""
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (
            (item.get("category") or "").upper(),
            item.get("source_excerpt") or "",
            (item.get("description") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Объединение отчётов по сегментам (FR-37, FR-62, раздел 13.4)
# ---------------------------------------------------------------------------

def _merge(reports: list[dict]) -> dict:
    merged = {
        "summary": "",
        "entities": [],
        "clauses": [],
        "warnings": [],
        "missing_information": [],
        "limitations": [],
    }
    summaries: list[str] = []
    for r in reports:
        if r.get("summary"):
            summaries.append(r["summary"])
        merged["entities"].extend(r.get("entities", []))
        merged["clauses"].extend(r.get("clauses", []))
        merged["warnings"].extend(r.get("warnings", []))
        merged["missing_information"].extend(r.get("missing_information", []))
        merged["limitations"].extend(r.get("limitations", []))

    merged["summary"] = " ".join(summaries) if summaries else ""
    merged["entities"] = _dedup_entities(merged["entities"])
    merged["clauses"] = _dedup_clauses(merged["clauses"])
    merged["warnings"] = _dedup_warnings(merged["warnings"])
    # Уникальные строки с сохранением порядка
    merged["missing_information"] = list(dict.fromkeys(merged["missing_information"]))
    merged["limitations"] = list(dict.fromkeys(merged["limitations"]))
    return merged


# ---------------------------------------------------------------------------
# Проверка и валидация цитат (FR-48, FR-51, FR-56, FR-58, FR-59)
# ---------------------------------------------------------------------------

def _validate_source_quotes(report: dict, source_text: str) -> dict:
    """Проставляет source_validation и нормализует source_excerpt.

    Для warnings отсутствие цитаты — осмысленный случай (предупреждения
    об отсутствии информации, FR-55 п.1, FR-59): статус not_applicable.
    """
    for key in ("entities", "clauses", "warnings"):
        for item in report.get(key, []):
            quote = item.get("source_excerpt")
            if isinstance(quote, str):
                quote = quote.strip() or None
            item["source_excerpt"] = quote

            if quote and quote in source_text:
                item["source_validation"] = "confirmed"
            elif quote is None and key == "warnings":
                item["source_validation"] = "not_applicable"
            else:
                item["source_validation"] = "unverified"
    return report


# ---------------------------------------------------------------------------
# Детерминированные проверки (этап 9 пайплайна, раздел 13.2)
# ---------------------------------------------------------------------------

def _deterministic_checks(report: dict, source_text: str) -> dict:
    """Проверки, которые надёжнее делать кодом, а не моделью.

    Покрывает FR-54, FR-55 и раздел 10.7 ТЗ (валидация).
    """
    warnings = report.setdefault("warnings", [])
    missing = report.setdefault("missing_information", [])

    # ---- 1. Проверка обязательных сущностей ----
    entity_names_lower = {(e.get("name") or "").lower() for e in report.get("entities", [])}
    landlord_keys = {"арендодатель", "наймодатель"}
    tenant_keys = {"наниматель", "арендатор"}
    has_landlord = bool(entity_names_lower & landlord_keys)
    has_tenant = bool(entity_names_lower & tenant_keys)

    if not has_landlord:
        missing.append("Сведения об арендодателе/наймодателе")
    if not has_tenant:
        missing.append("Сведения о нанимателе/арендаторе")

    # ---- 2. Проверка обязательных категорий положений ----
    categories = {c.get("category") for c in report.get("clauses", [])}
    if "TERM" not in categories:
        missing.append("Срок действия договора")
    if "RENT" not in categories:
        missing.append("Размер арендной платы")
    if "DEPOSIT" not in categories:
        # Депозит не всегда обязателен, но отсутствие — повод предупредить
        missing.append("Условие об обеспечительном платеже (депозите)")

    # ---- 3. Превращение missing_information в warnings (FR-55 п.1) ----
    existing_missing_descs = {
        w.get("description", "") for w in warnings if w.get("category") == "MISSING_INFORMATION"
    }
    for item in missing:
        desc = f"В договоре отсутствует ожидаемая информация: {item}"
        if desc in existing_missing_descs:
            continue
        warnings.append({
            "category": "MISSING_INFORMATION",
            "severity": "medium",
            "description": desc,
            "source_excerpt": None,   # цитаты не существует
            "recommendation": f"Рекомендуется уточнить: {item}",
        })

    # ---- 4. Согласованность денежных значений (упрощённо) ----
    rent_entities = [
        e for e in report.get("entities", [])
        if any(k in (e.get("name") or "").lower() for k in ("аренд", "плат", "стоим"))
    ]
    normalized_values = {
        (e.get("normalized_value") if e.get("normalized_value") is not None else e.get("value"))
        for e in rent_entities
    }
    normalized_values.discard(None)
    if len(normalized_values) > 1:
        warnings.append({
            "category": "INCONSISTENCY",
            "severity": "high",
            "description": f"Обнаружены различные значения, связанные с арендной платой: {sorted(normalized_values, key=str)}",
            "source_excerpt": next(
                (e.get("source_excerpt") for e in rent_entities if e.get("source_excerpt")), None
            ),
            "source_fragments": [
                e.get("source_excerpt") for e in rent_entities if e.get("source_excerpt")
            ],
            "recommendation": "Проверить согласованность указанных в договоре денежных сумм",
        })

    return report


# ---------------------------------------------------------------------------
# Метаданные отчёта (FR-40, FR-61 п.8, раздел 14.4)
# ---------------------------------------------------------------------------

def _build_meta(is_partial: bool) -> dict:
    return {
        "pipeline_version": "1.0",
        "prompt_version": PROMPT_VERSION,
        "model_id": settings.llm_model or None,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "is_partial": is_partial,
    }


# ---------------------------------------------------------------------------
# Главный пайплайн (FR-01..FR-62, раздел 13.2)
# ---------------------------------------------------------------------------

async def run_pipeline(path: str) -> dict:
    text = extract_docx_text(path)
    chunks = segment_text(text)

    logger.info(
        "pipeline.start path=%s chars=%d chunks=%d",
        path, len(text), len(chunks),
    )

    reports: list[dict] = []
    failed: list[int] = []
    for index, chunk in enumerate(chunks):
        try:
            reports.append(await analyze_chunk(chunk))
        except ValueError as exc:
            logger.warning("pipeline.chunk_failed index=%d err=%s", index, exc)
            failed.append(index)

    if not reports:
        raise RuntimeError(
            "Ни один фрагмент договора не проанализирован: LLM не вернул валидный JSON"
        )

    report = _merge(reports)
    report = _validate_source_quotes(report, text)
    report = _deterministic_checks(report, text)

    is_partial = bool(failed)
    if is_partial:
        report.setdefault("limitations", []).append(
            f"Проанализированы не все фрагменты (не обработаны: {failed}). Отчёт может быть неполным."
        )

    report["meta"] = _build_meta(is_partial=is_partial)

    validated = AnalysisReport.model_validate(report)

    logger.info(
        "pipeline.done entities=%d clauses=%d warnings=%d partial=%s",
        len(validated.entities),
        len(validated.clauses),
        len(validated.warnings),
        is_partial,
    )

    return validated.model_dump(mode="json")