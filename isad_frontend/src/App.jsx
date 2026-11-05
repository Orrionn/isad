import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, AlertCircle, AlertTriangle, ArrowUpRight, Check, CheckCircle2,
  ChevronRight, Clock3, CloudUpload, FileCheck2, FileText, FolderOpen,
  Gauge, Info, LoaderCircle, Menu, Plus, RefreshCw, Search, ShieldCheck,
  Sparkles, Trash2, X, Building2, ListChecks, ScanSearch, CircleHelp
} from 'lucide-react'

const API = import.meta.env.VITE_API_URL || ''
const statusInfo = {
  queued: ['В очереди', 'queued'],
  processing: ['Анализируется', 'processing'],
  completed: ['Готово', 'completed'],
  failed: ['Ошибка', 'failed'],
  idle: ['Не запускался', 'idle']
}
const fmtDate = (value) => value ? new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—'
const shortName = (name = '') => name.length > 30 ? `${name.slice(0, 26)}…${name.slice(name.lastIndexOf('.'))}` : name

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const apiKey = import.meta.env.VITE_API_KEY
  if (apiKey) headers.set('X-API-Key', apiKey)
  const response = await fetch(`${API}${path}`, { ...options, headers })
  if (!response.ok) {
    let message = `Ошибка ${response.status}`
    try {
      const data = await response.json()
      message = typeof data.detail === 'string' ? data.detail : data.detail?.message || message
    } catch {}
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

function Status({ status }) {
  const [label, cls] = statusInfo[status] || ['Неизвестно', 'failed']
  return <span className={`status status-${cls}`}><i />{label}</span>
}

function App() {
  const [documents, setDocuments] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [report, setReport] = useState(null)
  const [tab, setTab] = useState('overview')
  const [query, setQuery] = useState('')
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileRef = useRef(null)

  const selected = documents.find(d => d.id === selectedId) || null
  const refreshDocuments = useCallback(async (keep = true) => {
    const data = await request('/api/v1/documents')
    setDocuments(data)
    if (keep && selectedId && !data.some(d => d.id === selectedId)) setSelectedId(data[0]?.id ?? null)
    if (!selectedId && data.length) setSelectedId(data[0].id)
    return data
  }, [selectedId])

  useEffect(() => {
    refreshDocuments().catch(e => setError(`Не удалось загрузить документы: ${e.message}`))
  }, [])

  const loadSelected = useCallback(async (id) => {
    if (!id) { setAnalysis(null); setReport(null); return }
    setError('')
    setReport(null)
    setAnalysis(null)
    try {
      const doc = await request(`/api/v1/documents/${id}`)
      // The backend exposes analysis status through the latest analysis only after it is started.
      const list = await request('/api/v1/documents')
      setDocuments(list)
      setSelectedId(doc.id)
    } catch (e) { setError(e.message) }
  }, [])

  useEffect(() => {
    if (!selectedId) { setAnalysis(null); setReport(null); return }
    let alive = true
    async function getLatest() {
      try {
        // There is no endpoint for listing analyses, so the UI retains the analysis ID
        // after creating a job and reloads the report only for that active session.
        if (analysis?.document_id === selectedId && analysis.status === 'completed') {
          const data = await request(`/api/v1/analyses/${analysis.id}/report`)
          if (alive) setReport(data)
        }
      } catch {}
    }
    getLatest()
    return () => { alive = false }
  }, [selectedId])

  useEffect(() => {
    if (!analysis || !['queued', 'processing'].includes(analysis.status)) return
    const timer = setInterval(async () => {
      try {
        const updated = await request(`/api/v1/analyses/${analysis.id}`)
        setAnalysis(updated)
        if (updated.status === 'completed') {
          const data = await request(`/api/v1/analyses/${analysis.id}/report`)
          setReport(data)
          setNotice('Анализ завершён. Отчёт готов к просмотру.')
          setTab('overview')
        } else if (updated.status === 'failed') {
          setError(updated.error_message || 'Не удалось выполнить анализ.')
        }
      } catch (e) { setError(e.message) }
    }, 2500)
    return () => clearInterval(timer)
  }, [analysis?.id, analysis?.status])

  const uploadFile = async (file) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.docx')) {
      setError('Поддерживаются только документы формата DOCX.')
      return
    }
    setUploading(true); setError(''); setNotice('')
    const form = new FormData()
    form.append('file', file)
    try {
      const doc = await request('/api/v1/documents', { method: 'POST', body: form })
      const list = await request('/api/v1/documents')
      setDocuments(list)
      setSelectedId(doc.id)
      setAnalysis(null); setReport(null); setTab('overview')
      setNotice('Документ успешно добавлен в систему.')
    } catch (e) { setError(e.message) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const startAnalysis = async () => {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      const job = await request(`/api/v1/documents/${selected.id}/analysis`, { method: 'POST' })
      setAnalysis(job); setReport(null); setTab('overview')
      setNotice('Документ поставлен в очередь на анализ.')
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  const deleteDocument = async () => {
    if (!selected || !window.confirm(`Удалить документ «${selected.filename}» и все результаты его анализа?`)) return
    try {
      await request(`/api/v1/documents/${selected.id}`, { method: 'DELETE' })
      const list = await request('/api/v1/documents')
      setDocuments(list); setSelectedId(list[0]?.id ?? null)
      setAnalysis(null); setReport(null); setNotice('Документ удалён.')
    } catch (e) { setError(e.message) }
  }

  const filtered = useMemo(() => documents.filter(d => d.filename.toLowerCase().includes(query.toLowerCase())), [documents, query])
  const warnings = report?.warnings || []
  const highWarnings = warnings.filter(w => ['high', 'critical', 'высокая', 'критический'].includes(String(w.severity).toLowerCase())).length

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><ShieldCheck size={23}/></div>
        <div><strong>ИСАД</strong><span>Интеллектуальный анализ</span></div>
      </div>
      <div className="side-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <button className="side-link active"><Gauge size={18}/> Обзор системы</button>
      <button className="side-link" onClick={() => fileRef.current?.click()}><CloudUpload size={18}/> Загрузить договор</button>
      <div className="sidebar-bottom">
        <div className="security-card">
          <div className="security-icon"><ShieldCheck size={17}/></div>
          <div><b>Рабочая среда</b><span>Документы хранятся в системе</span></div>
        </div>
        <div className="sidebar-foot"><span className="online-dot"/> ИСАД <span>·</span> MVP 1.0</div>
      </div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div className="crumb"><span>Рабочее пространство</span><ChevronRight size={14}/><b>Обзор</b></div>
        <div className="top-actions"><span className="top-status"><i/> Система готова</span><div className="avatar">Д</div></div>
      </header>

      <div className="content">
        <section className="welcome">
          <div>
            <div className="eyebrow"><Sparkles size={14}/> ИНТЕЛЛЕКТУАЛЬНАЯ СИСТЕМА</div>
            <h1>Анализ договоров<br/><em>аренды</em></h1>
            <p>Загружайте документы, находите важные условия и потенциальные риски — в одном рабочем пространстве.</p>
          </div>
          <div className="welcome-art" aria-hidden="true">
            <div className="art-orbit orbit-one"/><div className="art-orbit orbit-two"/>
            <div className="art-document"><div className="art-doc-head"><span/><span/><span/></div><div className="art-lines"><i/><i/><i/><i/><i/></div><div className="art-highlight"><Check size={15}/> Анализ готов</div></div>
            <div className="art-spark spark-a">✦</div><div className="art-spark spark-b">✧</div>
          </div>
        </section>

        {error && <div className="alert alert-error"><AlertCircle size={18}/><span>{error}</span><button onClick={() => setError('')}><X size={16}/></button></div>}
        {notice && <div className="alert alert-success"><CheckCircle2 size={18}/><span>{notice}</span><button onClick={() => setNotice('')}><X size={16}/></button></div>}

        <section className="stats-grid">
          <div className="stat-card"><div className="stat-icon blue"><FileText size={19}/></div><div><span>Всего документов</span><strong>{documents.length}</strong></div><small>в библиотеке</small></div>
          <div className="stat-card"><div className="stat-icon violet"><ScanSearch size={19}/></div><div><span>Анализов запущено</span><strong>{analysis ? 1 : '—'}</strong></div><small>в текущем сеансе</small></div>
          <div className="stat-card"><div className="stat-icon amber"><AlertTriangle size={19}/></div><div><span>Найдено предупреждений</span><strong>{report ? warnings.length : '—'}</strong></div><small>{report ? `${highWarnings} высокого приоритета` : 'после анализа'}</small></div>
          <div className="stat-card"><div className="stat-icon green"><CheckCircle2 size={19}/></div><div><span>Состояние системы</span><strong className="system-value">Активна</strong></div><small>ожидает документов</small></div>
        </section>

        <div className="workspace-grid">
          <section className="panel documents-panel">
            <div className="panel-heading">
              <div><div className="section-kicker">БИБЛИОТЕКА</div><h2>Ваши документы</h2><p>Управляйте загруженными договорами</p></div>
              <button className="primary-btn compact" onClick={() => fileRef.current?.click()}><Plus size={16}/> Добавить</button>
            </div>
            <div className="searchbox"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск по названию..."/>{query && <button onClick={() => setQuery('')}><X size={14}/></button>}</div>
            <div className="document-list">
              {filtered.length ? filtered.map(doc => <button key={doc.id} className={`document-row ${selectedId === doc.id ? 'selected' : ''}`} onClick={() => { setSelectedId(doc.id); setAnalysis(null); setReport(null); setTab('overview'); setError('') }}>
                <div className="file-icon"><FileText size={19}/></div><div className="doc-meta"><b title={doc.filename}>{shortName(doc.filename)}</b><span>{fmtDate(doc.created_at)}</span></div><ChevronRight size={16} className="doc-chevron"/>
              </button>) : <div className="empty-docs"><FolderOpen size={25}/><b>{query ? 'Ничего не найдено' : 'Пока нет документов'}</b><span>{query ? 'Попробуйте изменить запрос' : 'Загрузите первый договор в формате DOCX'}</span></div>}
            </div>
            <div className="panel-foot"><span>{documents.length} из 100 документов</span><button onClick={() => refreshDocuments().catch(e => setError(e.message))}><RefreshCw size={14}/> Обновить</button></div>
          </section>

          <section className="panel detail-panel">
            {selected ? <>
              <div className="panel-heading detail-heading">
                <div><div className="section-kicker">КАРТОЧКА ДОКУМЕНТА</div><h2>Анализ договора</h2><p>Проверка содержания и структуры документа</p></div>
                <button className="icon-btn danger-hover" title="Удалить документ" onClick={deleteDocument}><Trash2 size={17}/></button>
              </div>
              <div className="selected-file"><div className="file-icon large"><FileCheck2 size={22}/></div><div className="selected-meta"><b>{selected.filename}</b><span>DOCX · Добавлен {fmtDate(selected.created_at)}</span></div><Status status={analysis?.status || 'idle'} /></div>
              {!analysis && <div className="start-box"><div className="start-symbol"><Sparkles size={23}/></div><div><b>Готовы начать анализ?</b><p>Система изучит документ и подготовит сводку, выделит условия и потенциальные риски.</p></div><button className="primary-btn" onClick={startAnalysis} disabled={busy}>{busy ? <LoaderCircle className="spin" size={17}/> : <ScanSearch size={17}/>} Запустить анализ</button></div>}
              {analysis && ['queued', 'processing'].includes(analysis.status) && <div className="progress-box"><div className="progress-head"><div className="progress-spinner"><LoaderCircle className="spin" size={20}/></div><div><b>{analysis.status === 'queued' ? 'Документ ожидает обработки' : 'Идёт интеллектуальный анализ'}</b><span>{analysis.status === 'queued' ? 'Задача добавлена в очередь' : 'Извлекаем условия и проверяем содержание'}</span></div></div><div className="progress-track"><i/></div><div className="progress-note"><span>Это может занять несколько минут</span><span>Обновление автоматически</span></div></div>}
              {analysis?.status === 'failed' && <div className="failed-box"><AlertTriangle size={20}/><div><b>Не удалось завершить анализ</b><p>{analysis.error_message || 'Попробуйте запустить анализ ещё раз.'}</p></div><button className="secondary-btn" onClick={startAnalysis}>Повторить</button></div>}
              {report && <div className="report-area">
                <div className="report-topline"><div><span className="complete-mark"><Check size={13}/></span><b>Отчёт сформирован</b></div><span>{fmtDate(analysis?.created_at)}</span></div>
                <div className="tabs"><button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>Обзор</button><button className={tab === 'clauses' ? 'active' : ''} onClick={() => setTab('clauses')}>Положения <span>{report.clauses?.length || 0}</span></button><button className={tab === 'warnings' ? 'active' : ''} onClick={() => setTab('warnings')}>Риски <span>{warnings.length}</span></button><button className={tab === 'entities' ? 'active' : ''} onClick={() => setTab('entities')}>Сущности <span>{report.entities?.length || 0}</span></button></div>
                {tab === 'overview' && <div className="report-content"><h3>Краткое содержание</h3><p className="summary-text">{report.summary || 'Краткое содержание отсутствует.'}</p><div className="report-metrics"><div><span>Положения</span><b>{report.clauses?.length || 0}</b></div><div><span>Предупреждения</span><b>{warnings.length}</b></div><div><span>Сущности</span><b>{report.entities?.length || 0}</b></div></div>{report.missing_information?.length > 0 && <div className="info-block"><b><Info size={15}/> Не хватает информации</b><ul>{report.missing_information.map((x,i)=><li key={i}>{x}</li>)}</ul></div>}{report.limitations?.length > 0 && <p className="disclaimer"><Info size={14}/> {report.limitations.join(' ')}</p>}</div>}
                {tab === 'clauses' && <div className="report-content">{report.clauses?.length ? report.clauses.map((c,i)=><div className="result-item" key={i}><div className="result-title"><b>{c.category}</b><span>{Math.round((c.confidence ?? 0)*100)}% уверенности</span></div><p>{c.summary}</p><blockquote>{c.source_excerpt}</blockquote></div>) : <div className="empty-result">Классифицированные положения не найдены.</div>}</div>}
                {tab === 'warnings' && <div className="report-content">{warnings.length ? warnings.map((w,i)=><div className="result-item warning-item" key={i}><div className="result-title"><b><AlertTriangle size={15}/>{w.category}</b><span className={`severity severity-${String(w.severity).toLowerCase()}`}>{w.severity}</span></div><p>{w.description}</p><blockquote>{w.source_excerpt}</blockquote>{w.recommendation && <div className="recommendation"><b>Рекомендация</b><span>{w.recommendation}</span></div>}</div>) : <div className="empty-result"><CheckCircle2 size={20}/> Предупреждений не обнаружено.</div>}</div>}
                {tab === 'entities' && <div className="report-content">{report.entities?.length ? report.entities.map((entity,i)=><div className="entity-row" key={i}><div className="entity-icon"><Building2 size={16}/></div><div><b>{entity.name}</b><span>{entity.value || 'Значение не указано'}</span><small>«{entity.source_excerpt}»</small></div></div>) : <div className="empty-result">Сущности не обнаружены.</div>}</div>}
              </div>}
              {!report && <div className="hint-line"><ShieldCheck size={15}/> Результаты анализа появятся здесь после обработки документа.</div>}
            </> : <div className="detail-empty"><div className="empty-illustration"><FileText size={32}/><Sparkles size={18}/></div><h2>Выберите документ</h2><p>Выберите договор из библиотеки слева или загрузите новый, чтобы начать работу.</p><button className="primary-btn" onClick={() => fileRef.current?.click()}><CloudUpload size={17}/> Загрузить договор</button></div>}
          </section>
        </div>
        <footer className="page-footer"><span>ИСАД · Интеллектуальная система анализа договоров аренды</span><span><CircleHelp size={14}/> Технический анализ текста, не юридическое заключение</span></footer>
      </div>
    </main>

    <input ref={fileRef} type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden onChange={e => uploadFile(e.target.files?.[0])}/>
    {uploading && <div className="upload-overlay"><div className="upload-modal"><LoaderCircle className="spin" size={27}/><b>Загружаем документ</b><span>Пожалуйста, не закрывайте страницу</span></div></div>}
  </div>
}

export default App
