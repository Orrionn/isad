from docx import Document as WordDocument

def extract_docx_text(path: str) -> str:
    doc = WordDocument(path)
    parts: list[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)
    for table_index, table in enumerate(doc.tables, start=1):
        parts.append(f"[Таблица {table_index}]")
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    result = "\n".join(parts).strip()
    if not result:
        raise ValueError("В DOCX не найден текст для анализа")
    return result

def segment_text(text: str, max_chars: int = 10000) -> list[str]:
    # Простая MVP-сегментация по абзацам с сохранением границ. Можно улучшить
    # разбором заголовков и нумерованных пунктов на следующем этапе.
    chunks, current = [], ""
    for paragraph in text.splitlines():
        if current and len(current) + len(paragraph) + 1 > max_chars:
            chunks.append(current)
            current = ""
        current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks
