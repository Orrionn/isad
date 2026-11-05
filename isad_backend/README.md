# ИСАД — backend MVP

Backend-каркас: FastAPI + PostgreSQL + SQLAlchemy + Alembic + Redis + Celery.
Документы `.docx`; AI-логика выполняется в отдельном worker-процессе.

## Запуск
1. Установите Docker Desktop и Docker Compose.
2. Скопируйте `.env.example` в `.env` и заполните `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`.
3. `docker compose up --build`
4. API: http://localhost:8000
5. Swagger: http://localhost:8000/docs
6. Проверка состояния: http://localhost:8000/health

> Первый каркас требует проверки и доработки в рамках реализации. Не загружайте реальные договоры с персональными данными в сторонний API без разрешения.

## MVP endpoints
- `POST /api/v1/documents` — загрузка DOCX
- `GET /api/v1/documents` — список документов
- `GET /api/v1/documents/{document_id}` — метаданные документа
- `DELETE /api/v1/documents/{document_id}` — удаление документа и результатов
- `POST /api/v1/documents/{document_id}/analysis` — поставить анализ в очередь
- `GET /api/v1/analyses/{analysis_id}` — статус анализа
- `GET /api/v1/analyses/{analysis_id}/report` — отчёт
- `GET /api/v1/documents/{document_id}/entities` — сущности
- `GET /api/v1/documents/{document_id}/clauses` — классифицированные положения
- `GET /api/v1/documents/{document_id}/warnings` — предупреждения

## Структура
`app/api` — маршруты; `app/models` — ORM; `app/schemas` — Pydantic;
`app/services` — прикладная логика; `app/worker` — Celery; `app/ai` — парсер, промпт и LLM-клиент.
