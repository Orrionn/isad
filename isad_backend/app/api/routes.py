import hashlib
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models import Analysis, AnalysisStatus, Document
from app.schemas import AnalysisOut, DocumentOut
from app.worker.tasks import analyze_document_task

router = APIRouter(prefix="/api/v1")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".docx"):
        raise HTTPException(415, "Поддерживаются только файлы DOCX")
    content = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(400, "Файл пуст")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Максимальный размер файла: {settings.max_upload_mb} МБ")
    # DOCX — ZIP-контейнер; проверяем сигнатуру, не полагаемся только на расширение.
    if not content.startswith(b"PK"):
        raise HTTPException(400, "Файл не похож на корректный DOCX")
    sha = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(select(Document).where(Document.sha256 == sha))
    if duplicate:
        return duplicate
    os.makedirs(settings.upload_dir, exist_ok=True)
    stored = str(Path(settings.upload_dir) / f"{uuid.uuid4().hex}.docx")
    with open(stored, "wb") as output:
        output.write(content)
    document = Document(filename=filename, stored_path=stored, sha256=sha, content_type=DOCX_MIME)
    db.add(document)
    db.commit()
    db.refresh(document)
    return document

@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    return list(db.scalars(select(Document).order_by(Document.id.desc()).limit(100)))

@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Документ не найден")
    return document

@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Документ не найден")
    try:
        Path(document.stored_path).unlink(missing_ok=True)
    finally:
        db.delete(document)
        db.commit()
    return None

@router.post("/documents/{document_id}/analysis", response_model=AnalysisOut, status_code=202)
def start_analysis(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Документ не найден")
    analysis = Analysis(document_id=document.id, status=AnalysisStatus.queued)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    try:
        analyze_document_task.delay(analysis.id)
    except Exception as exc:
        analysis.status = AnalysisStatus.failed
        analysis.error_message = f"Не удалось поставить задачу в очередь: {exc}"
        db.commit()
        raise HTTPException(503, "Очередь задач недоступна")
    return analysis

@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        raise HTTPException(404, "Задание не найдено")
    return analysis

@router.get("/analyses/{analysis_id}/report")
def get_report(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        raise HTTPException(404, "Задание не найдено")
    if analysis.status == AnalysisStatus.failed:
        raise HTTPException(409, detail={"message": "Анализ завершился ошибкой", "error": analysis.error_message})
    if analysis.status != AnalysisStatus.completed or analysis.report is None:
        raise HTTPException(202, "Отчёт ещё не готов")
    return analysis.report

def _get_latest_report(document_id: int, db: Session):
    analysis = db.scalar(select(Analysis).where(
        Analysis.document_id == document_id,
        Analysis.status == AnalysisStatus.completed
    ).order_by(Analysis.id.desc()))
    if not analysis or not analysis.report:
        raise HTTPException(404, "Завершённый отчёт не найден")
    return analysis.report

@router.get("/documents/{document_id}/entities")
def get_entities(document_id: int, db: Session = Depends(get_db)):
    return _get_latest_report(document_id, db).get("entities", [])

@router.get("/documents/{document_id}/clauses")
def get_clauses(document_id: int, db: Session = Depends(get_db)):
    return _get_latest_report(document_id, db).get("clauses", [])

@router.get("/documents/{document_id}/warnings")
def get_warnings(document_id: int, db: Session = Depends(get_db)):
    return _get_latest_report(document_id, db).get("warnings", [])
