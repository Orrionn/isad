import asyncio
import logging
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Analysis, AnalysisStatus, Document
from app.ai.pipeline import run_pipeline
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, autoretry_for=(TimeoutError, ConnectionError),
                 retry_backoff=True, retry_kwargs={"max_retries": 3})
def analyze_document_task(self, analysis_id: int):
    db = SessionLocal()
    try:
        analysis = db.get(Analysis, analysis_id)
        if not analysis:
            logger.error("Analysis %s not found", analysis_id)
            return
        document = db.get(Document, analysis.document_id)
        analysis.status = AnalysisStatus.processing
        analysis.error_message = None
        db.commit()
        report = asyncio.run(run_pipeline(document.stored_path))
        analysis.report = report
        analysis.status = AnalysisStatus.completed
        db.commit()
    except Exception as exc:
        db.rollback()
        analysis = db.get(Analysis, analysis_id)
        if analysis:
            analysis.status = AnalysisStatus.failed
            analysis.error_message = str(exc)[:2000]
            db.commit()
        logger.exception("Analysis %s failed", analysis_id)
        raise
    finally:
        db.close()
