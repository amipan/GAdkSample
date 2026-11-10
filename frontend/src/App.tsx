import { useEffect, useState } from 'react'
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronRight,
  FileText,
  History,
  Info,
  Landmark,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  X,
} from 'lucide-react'
import './App.css'

type FieldName = 'borrower_name' | 'loan_number'
type ActiveTab = 'pending' | 'completed' | 'rejections'

type Attribution = {
  borrower_name?: string | null
  loan_number?: string | null
  borrower_name_confidence?: number
  loan_number_confidence?: number
  borrower_name_rationale?: string
  loan_number_rationale?: string
  borrower_name_evidence_quote?: string | null
  loan_number_evidence_quote?: string | null
  borrower_name_page_number?: number | null
  loan_number_page_number?: number | null
  evidence_quote?: string | null
  page_number?: number | null
  validation_status?: string
  borrower_name_validation_issues?: string[]
  loan_number_validation_issues?: string[]
}

type WorkflowRun = {
  thread_id: string
  status?: string
  random_number: number | null
  borrower_name?: string | null
  loan_number?: string | null
  classified_file?: string | null
  steps: string[]
  created_at: string
  updated_at?: string
  field_extraction_result?: Attribution | null
}

type WorkflowResponse = WorkflowRun & {
  status: string
  interrupt?: { message?: string } | null
}

type Rejection = {
  thread_id: string
  file_name: string
  rejected_at: string
  borrower_name?: string | null
  loan_number?: string | null
  classified_file?: string | null
}

type AttributionDetails = {
  label: string
  value: string
  confidence?: number
  rationale: string
  evidence: string
  page?: number | null
  validationStatus: string
  validationIssues: string[]
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload && typeof payload.detail === 'string'
      ? payload.detail
      : `Request failed with status ${response.status}`
    throw new Error(detail)
  }
  return payload as T
}

function getAttributionDetails(run: WorkflowRun, field: FieldName): AttributionDetails {
  const result = run.field_extraction_result
  const borrower = field === 'borrower_name'
  return {
    label: borrower ? 'Borrower' : 'Loan number',
    value: result?.[field] || 'Not found',
    confidence: borrower ? result?.borrower_name_confidence : result?.loan_number_confidence,
    rationale: borrower ? result?.borrower_name_rationale || '' : result?.loan_number_rationale || '',
    evidence: borrower
      ? result?.borrower_name_evidence_quote || result?.evidence_quote || ''
      : result?.loan_number_evidence_quote || '',
    page: borrower
      ? result?.borrower_name_page_number ?? result?.page_number
      : result?.loan_number_page_number,
    validationStatus: result?.validation_status || 'Not available',
    validationIssues: borrower
      ? result?.borrower_name_validation_issues || []
      : result?.loan_number_validation_issues || [],
  }
}

function formatDate(value: string | undefined) {
  if (!value) return 'Time unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('pending')
  const [pendingRuns, setPendingRuns] = useState<WorkflowRun[]>([])
  const [completedRuns, setCompletedRuns] = useState<WorkflowRun[]>([])
  const [rejections, setRejections] = useState<Rejection[]>([])
  const [selectedThreadId, setSelectedThreadId] = useState('')
  const [borrowerName, setBorrowerName] = useState('')
  const [loanNumber, setLoanNumber] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [pendingLoading, setPendingLoading] = useState(true)
  const [completedLoading, setCompletedLoading] = useState(false)
  const [rejectionsLoading, setRejectionsLoading] = useState(false)
  const [detailsField, setDetailsField] = useState<FieldName | null>(null)
  const [confirmRejection, setConfirmRejection] = useState<string | null>(null)

  const selectedRun = pendingRuns.find((run) => run.thread_id === selectedThreadId)

  async function refreshPending(preferredThreadId?: string) {
    setPendingLoading(true)
    try {
      const { runs } = await requestJson<{ runs: WorkflowRun[] }>('/workflows/pending')
      setPendingRuns(runs)
      const nextId = runs.find((run) => run.thread_id === preferredThreadId)?.thread_id
        || runs.find((run) => run.thread_id === selectedThreadId)?.thread_id
        || runs[0]?.thread_id
        || ''
      setSelectedThreadId(nextId)
      const selected = runs.find((run) => run.thread_id === nextId)
      setBorrowerName(selected?.borrower_name || '')
      setLoanNumber(selected?.loan_number || '')
      if (!nextId) setDetailsField(null)
      setError('')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load pending approvals.')
    } finally {
      setPendingLoading(false)
    }
  }

  async function refreshCompleted() {
    setCompletedLoading(true)
    try {
      const { runs } = await requestJson<{ runs: WorkflowRun[] }>('/workflows/completed')
      setCompletedRuns(runs)
      setError('')
      return runs.length
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load workflow history.')
      return null
    } finally {
      setCompletedLoading(false)
    }
  }

  async function refreshRejections() {
    setRejectionsLoading(true)
    try {
      const { runs } = await requestJson<{ runs: Rejection[] }>('/workflows/rejections')
      setRejections(runs)
      setError('')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load rejections.')
    } finally {
      setRejectionsLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    async function loadInitialData() {
      try {
        const { runs } = await requestJson<{ runs: WorkflowRun[] }>('/workflows/pending')
        if (active) {
          setPendingRuns(runs)
          const firstRun = runs[0]
          setSelectedThreadId(firstRun?.thread_id || '')
          setBorrowerName(firstRun?.borrower_name || '')
          setLoanNumber(firstRun?.loan_number || '')
        }
      } catch (requestError) {
        if (active) setError(requestError instanceof Error ? requestError.message : 'Could not load pending approvals.')
      } finally {
        if (active) setPendingLoading(false)
      }

      try {
        const { runs } = await requestJson<{ runs: WorkflowRun[] }>('/workflows/completed')
        if (active) setCompletedRuns(runs)
      } catch (requestError) {
        if (active) setError(requestError instanceof Error ? requestError.message : 'Could not load workflow history.')
      }

      try {
        const { runs } = await requestJson<{ runs: Rejection[] }>('/workflows/rejections')
        if (active) setRejections(runs)
      } catch (requestError) {
        if (active) setError(requestError instanceof Error ? requestError.message : 'Could not load rejections.')
      }
    }
    void loadInitialData()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!confirmRejection) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !busyAction) setConfirmRejection(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [confirmRejection, busyAction])

  function selectRun(run: WorkflowRun) {
    setSelectedThreadId(run.thread_id)
    setBorrowerName(run.borrower_name || '')
    setLoanNumber(run.loan_number || '')
    setDetailsField(null)
    setError('')
  }

  async function decideWorkflow(decision: 'approve' | 'reject', threadId = selectedThreadId) {
    if (!threadId) return
    setBusyAction(decision)
    setError('')
    setNotice(decision === 'approve' ? 'Approving workflow…' : 'Rejecting workflow…')
    try {
      const result = await requestJson<WorkflowResponse>(
        `/workflows/${encodeURIComponent(threadId)}/${decision}`,
        {
          method: 'POST',
          ...(decision === 'approve'
            ? { body: JSON.stringify({ borrower_name: borrowerName, loan_number: loanNumber }) }
            : {}),
        },
      )
      await refreshPending(result.status === 'waiting_for_approval' ? threadId : undefined)
      await refreshCompleted()
      if (decision === 'reject') await refreshRejections()
      setActiveTab(result.status === 'waiting_for_approval' ? 'pending' : decision === 'reject' ? 'rejections' : 'completed')
      setNotice(result.status === 'waiting_for_approval'
        ? 'The workflow returned for another review.'
        : decision === 'approve' ? 'Workflow approved and completed.' : 'Workflow rejected and recorded.')
      setDetailsField(null)
      setConfirmRejection(null)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : `Could not ${decision} workflow.`)
      setNotice('The decision outcome could not be confirmed. Refresh the workflow lists before retrying.')
    } finally {
      setBusyAction('')
    }
  }

  function showFieldDetails(field: FieldName) {
    if (!selectedRun?.field_extraction_result) {
      setError('Attribution details are not available for this run.')
      return
    }
    setDetailsField(field)
  }

  const details = detailsField && selectedRun
    ? getAttributionDetails(selectedRun, detailsField)
    : null

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand-lockup" href="#home" aria-label="Wells Fargo workflow home">
          <span className="brand-emblem" aria-hidden="true"><Landmark size={21} strokeWidth={2.2} /></span>
          <span className="brand-name">Wells Fargo</span>
          <span className="brand-divider" />
          <span className="brand-product">Business lending</span>
        </a>
        <div className="topbar-meta">
          <span className="environment-pill"><span />Local workflow</span>
          <span className="prototype-note">User: DocManager</span>
        </div>
      </header>

      <main id="home" className="workspace">
        <div className="page-heading">
          <div>
            <p className="eyebrow">DOCUMENT OPERATIONS <span> / </span> HUMAN REVIEW</p>
            <h1>Workflow approvals</h1>
            <p className="page-description">Review fields attribution and keep each document moving.</p>
          </div>
        </div>

        {notice && <p className="workflow-notice" role="status">{notice}</p>}

        {error && (
          <div className="alert alert-error" role="alert">
            <AlertCircle size={18} />
            <span>{error}</span>
            <button type="button" className="icon-button alert-close" aria-label="Dismiss message" onClick={() => setError('')}><X size={16} /></button>
          </div>
        )}

        <div className="workbench">
          <aside className="queue-panel" aria-label="Workflow queue">
            <div className="queue-heading">
              <div>
                <p className="section-kicker">YOUR QUEUE</p>
                <h2>Workflows</h2>
              </div>
              <button
                className="icon-button refresh-button"
                type="button"
                title="Refresh workflow list"
                aria-label="Refresh workflow list"
                onClick={() => activeTab === 'pending' ? void refreshPending() : activeTab === 'completed' ? void refreshCompleted() : void refreshRejections()}
                disabled={pendingLoading || completedLoading || rejectionsLoading}
              >
                <RefreshCw size={17} className={pendingLoading || completedLoading || rejectionsLoading ? 'spin' : ''} />
              </button>
            </div>

            <div className="view-tabs" role="tablist" aria-label="Workflow views">
              <button className={activeTab === 'pending' ? 'view-tab active' : 'view-tab'} role="tab" aria-selected={activeTab === 'pending'} onClick={() => setActiveTab('pending')}>
                Pending <span className="tab-count">{pendingRuns.length}</span>
              </button>
              <button className={activeTab === 'completed' ? 'view-tab active' : 'view-tab'} role="tab" aria-selected={activeTab === 'completed'} onClick={() => setActiveTab('completed')}>
                History <span className="tab-count">{completedRuns.length}</span>
              </button>
              <button className={activeTab === 'rejections' ? 'view-tab active' : 'view-tab'} role="tab" aria-selected={activeTab === 'rejections'} onClick={() => { setActiveTab('rejections'); void refreshRejections() }}>
                Rejections <span className="tab-count">{rejections.length}</span>
              </button>
            </div>

            {activeTab === 'pending' ? (
              <div className="queue-list">
                {pendingLoading && pendingRuns.length === 0 ? (
                  <div className="queue-empty"><LoaderCircle className="spin" size={20} /><span>Loading approvals</span></div>
                ) : pendingRuns.length ? pendingRuns.map((run) => (
                  <button
                    type="button"
                    key={run.thread_id}
                    className={run.thread_id === selectedThreadId ? 'queue-item selected' : 'queue-item'}
                    onClick={() => selectRun(run)}
                  >
                    <span className="queue-item-top"><span className="queue-status"><span />Pending review</span><ChevronRight size={16} /></span>
                    <span className="queue-file"><FileText size={16} />{run.classified_file || 'Unclassified document'}</span>
                    <span className="queue-item-bottom"><span>#{run.thread_id.slice(0, 8)}</span><span>{formatDate(run.created_at)}</span></span>
                  </button>
                )) : (
                  <div className="queue-empty">
                    <span className="empty-mark"><Check size={18} /></span>
                    <strong>Queue is clear</strong>
                    <span>No pending approvals right now.</span>
                  </div>
                )}
              </div>
            ) : activeTab === 'completed' ? (
              <div className="queue-list history-list">
                {completedLoading && completedRuns.length === 0 ? (
                  <div className="queue-empty"><LoaderCircle className="spin" size={20} /><span>Loading history</span></div>
                ) : completedRuns.length ? completedRuns.map((run) => (
                  <div className="history-item" key={run.thread_id}>
                    <span className={run.status === 'approved' ? 'history-status approved' : 'history-status'}>
                      {run.status === 'approved' ? <Check size={13} /> : <History size={13} />}
                      {run.status || 'Completed'}
                    </span>
                    <strong>{run.borrower_name || 'Borrower not identified'}</strong>
                    <span>{run.classified_file || 'Unclassified document'}</span>
                    <small>{formatDate(run.updated_at || run.created_at)}</small>
                  </div>
                )) : (
                  <div className="queue-empty"><History size={20} /><span>No completed workflows yet.</span></div>
                )}
              </div>
            ) : (
              <div className="queue-list history-list">
                {rejectionsLoading && rejections.length === 0 ? (
                  <div className="queue-empty"><LoaderCircle className="spin" size={20} /><span>Loading rejections</span></div>
                ) : rejections.length ? rejections.map((rejection) => (
                  <div className="history-item" key={rejection.thread_id}>
                    <span className="history-status"><X size={13} />Rejected</span>
                    <strong>{rejection.borrower_name || 'Borrower not identified'}</strong>
                    <span>{rejection.classified_file || 'Unclassified document'}</span>
                    <small>{formatDate(rejection.rejected_at)}</small>
                  </div>
                )) : (
                  <div className="queue-empty"><History size={20} /><span>No rejected workflows yet.</span></div>
                )}
              </div>
            )}

            <div className="queue-footnote"><ShieldCheck size={15} /> Review changes are saved with the workflow record.</div>
          </aside>

          <section className="review-panel" aria-label="Selected workflow review">
            {activeTab === 'rejections' ? (
              <div className="history-view">
                <div className="panel-heading">
                  <div>
                    <p className="section-kicker">REJECTION RECORDS</p>
                    <h2>Rejected workflows</h2>
                    <p>Documents rejected during human review.</p>
                  </div>
                  <button className="button button-secondary" onClick={() => void refreshRejections()} disabled={rejectionsLoading}>
                    <RefreshCw size={16} className={rejectionsLoading ? 'spin' : ''} />Refresh
                  </button>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Rejected</th><th>Thread ID</th><th>File name</th><th>Classification</th><th>Borrower</th><th>Loan number</th></tr></thead>
                    <tbody>
                      {rejections.map((rejection) => (
                        <tr key={rejection.thread_id}>
                          <td>{formatDate(rejection.rejected_at)}</td>
                          <td><code>{rejection.thread_id.slice(0, 10)}</code></td>
                          <td className="rejection-file-name">{rejection.file_name}</td>
                          <td>{rejection.classified_file || '—'}</td>
                          <td>{rejection.borrower_name || '—'}</td>
                          <td>{rejection.loan_number || '—'}</td>
                        </tr>
                      ))}
                      {!rejections.length && <tr><td className="table-empty" colSpan={6}>No rejected workflows to display.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : activeTab === 'completed' ? (
              <div className="history-view">
                <div className="panel-heading">
                  <div>
                    <p className="section-kicker">RUN RECORDS</p>
                    <h2>Completed workflows</h2>
                    <p>Latest finalized runs from the workflow registry.</p>
                  </div>
                  <button className="button button-secondary" onClick={() => void refreshCompleted()} disabled={completedLoading}>
                    <RefreshCw size={16} className={completedLoading ? 'spin' : ''} />Refresh
                  </button>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Finished</th><th>Thread ID</th><th>Status</th><th>Classification</th><th>Borrower</th><th>Loan number</th><th>Random #</th><th>Steps</th></tr></thead>
                    <tbody>
                      {completedRuns.map((run) => (
                        <tr key={run.thread_id}>
                          <td>{formatDate(run.updated_at || run.created_at)}</td>
                          <td><code>{run.thread_id.slice(0, 10)}</code></td>
                          <td><span className={run.status === 'approved' ? 'table-status approved' : 'table-status'}>{run.status || 'completed'}</span></td>
                          <td>{run.classified_file || '—'}</td>
                          <td>{run.borrower_name || '—'}</td>
                          <td>{run.loan_number || '—'}</td>
                          <td>{run.random_number ?? '—'}</td>
                          <td className="steps-cell" title={run.steps.join(' · ')}>{run.steps.join(' · ') || '—'} <ArrowUpRight size={13} /></td>
                        </tr>
                      ))}
                      {!completedRuns.length && <tr><td className="table-empty" colSpan={8}>No completed workflows to display.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : selectedRun ? (
              <>
                <div className="panel-heading review-heading">
                  <div>
                    <p className="section-kicker">PENDING REVIEW <span className="heading-separator">/</span> {selectedRun.classified_file || 'UNCLASSIFIED'}</p>
                    <h2>Fields attribution</h2>
                    <p>Confirm the extracted values before continuing the workflow.</p>
                  </div>
                  <span className="review-badge"><span />Needs review</span>
                </div>

                <div className="metadata-row">
                  <div><span>Thread</span><code>{selectedRun.thread_id}</code></div>
                  <div><span>Started</span><strong>{formatDate(selectedRun.created_at)}</strong></div>
                  <div><span>Classification</span><strong>{selectedRun.classified_file || 'Not available'}</strong></div>
                </div>

                <div className="review-fields">
                  <div className="field-block">
                    <label htmlFor="borrower-name">Borrower name</label>
                    <div className="field-control">
                      <input id="borrower-name" value={borrowerName} onChange={(event) => setBorrowerName(event.target.value)} placeholder="Enter borrower name" />
                      <button type="button" className="field-info" onClick={() => showFieldDetails('borrower_name')} aria-label="Show field attribution details" title="Field attribution details"><Info size={17} /></button>
                    </div>
                    <span className="field-hint">Edit if the document identifies a different borrower.</span>
                  </div>
                  <div className="field-block">
                    <label htmlFor="loan-number">Loan number</label>
                    <div className="field-control">
                      <input id="loan-number" value={loanNumber} onChange={(event) => setLoanNumber(event.target.value)} placeholder="Enter loan number" />
                      <button type="button" className="field-info" onClick={() => showFieldDetails('loan_number')} aria-label="Show field attribution details" title="Field attribution details"><Info size={17} /></button>
                    </div>
                    <span className="field-hint">Keep leading zeroes if they appear in the source.</span>
                  </div>
                </div>

                <div className="review-note">
                  <span className="note-icon"><Info size={17} /></span>
                  <p><strong>Review the source evidence.</strong> The confidence score is the model’s estimate, not a calibrated probability.</p>
                </div>

                <div className="decision-bar">
                  <div className="decision-copy"><strong>Ready to decide?</strong><span>Approval continues the workflow. Rejection records the document and ends the run.</span></div>
                  <div className="decision-actions">
                    <button className="button button-reject" onClick={() => { setError(''); setConfirmRejection(selectedThreadId) }} disabled={Boolean(busyAction)}>
                      {busyAction === 'reject' ? <LoaderCircle className="spin" size={16} /> : <X size={16} />}Reject
                    </button>
                    <button className="button button-approve" onClick={() => void decideWorkflow('approve')} disabled={Boolean(busyAction)}>
                      {busyAction === 'approve' ? <LoaderCircle className="spin" size={16} /> : <Check size={17} />}Approve
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div className="no-selection">
                <div className="no-selection-icon"><Landmark size={25} /></div>
                <p className="section-kicker">PENDING APPROVALS</p>
                <h2>{pendingLoading ? 'Loading your queue' : 'Nothing needs your attention'}</h2>
                <p>{pendingLoading ? 'Checking the workflow service for runs.' : 'No workflows are currently waiting for review.'}</p>
              </div>
            )}
          </section>
        </div>

        <footer className="page-footer">
          <span><ShieldCheck size={15} /> Secure workflow review</span>
          <span>Wells Fargo brand colors · Independent prototype, not an official Wells Fargo product</span>
        </footer>
      </main>

      {confirmRejection && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyAction) setConfirmRejection(null) }}>
          <section className="details-dialog" role="dialog" aria-modal="true" aria-labelledby="reject-title">
            <div className="dialog-topline" />
            <header className="dialog-header">
              <div className="dialog-icon"><AlertCircle size={19} /></div>
              <div><p className="section-kicker">CONFIRM DECISION</p><h2 id="reject-title">Reject this workflow?</h2></div>
              <button type="button" className="icon-button dialog-close" aria-label="Close rejection confirmation" onClick={() => setConfirmRejection(null)} disabled={Boolean(busyAction)}><X size={19} /></button>
            </header>
            <div className="dialog-section"><p>The file name for workflow {confirmRejection} will be recorded and this workflow will end.</p></div>
            {error && <div className="alert alert-error dialog-error" role="alert"><AlertCircle size={18} /><span>{error}</span></div>}
            <div className="decision-actions dialog-done">
              <button className="button button-secondary" onClick={() => setConfirmRejection(null)} disabled={Boolean(busyAction)} autoFocus>Cancel</button>
              <button className="button button-reject" onClick={() => void decideWorkflow('reject', confirmRejection)} disabled={Boolean(busyAction)}>
                {busyAction === 'reject' ? <LoaderCircle className="spin" size={16} /> : <X size={16} />}Confirm rejection
              </button>
            </div>
          </section>
        </div>
      )}

      {details && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetailsField(null) }}>
          <section className="details-dialog" role="dialog" aria-modal="true" aria-labelledby="details-title">
            <div className="dialog-topline" />
            <header className="dialog-header">
              <div className="dialog-icon"><Info size={19} /></div>
              <div><p className="section-kicker">ATTRIBUTION DETAILS</p><h2 id="details-title">{details.label}</h2></div>
              <button type="button" className="icon-button dialog-close" aria-label="Close attribution details" onClick={() => setDetailsField(null)}><X size={19} /></button>
            </header>
            <div className="dialog-result"><span>Extracted value</span><strong>{details.value}</strong></div>
            <div className="confidence-row"><span>Model confidence</span><strong>{typeof details.confidence === 'number' ? `${Math.round(details.confidence * 100)}%` : 'Not available'}</strong></div>
            <div className="confidence-meter" aria-label={typeof details.confidence === 'number' ? `${Math.round(details.confidence * 100)} percent confidence` : 'Confidence unavailable'}><span style={{ width: `${Math.min(100, Math.max(0, (details.confidence || 0) * 100))}%` }} /></div>
            <div className="dialog-section"><span>Rationale</span><p>{details.rationale || 'Field-specific rationale is not available for this result.'}</p></div>
            <div className="dialog-section"><span>Source evidence{details.page ? ` · Page ${details.page}` : ''}</span><blockquote>{details.evidence ? `“${details.evidence}”` : 'No evidence quote was returned.'}</blockquote></div>
            <div className="dialog-validation"><span className={details.validationStatus === 'EVIDENCE_VERIFIED' ? 'verified-dot' : 'unverified-dot'} />
              <div><strong>{details.validationStatus}</strong>{details.validationIssues.length > 0 && <p>{details.validationIssues.join('; ')}</p>}</div>
            </div>
            <button className="button button-secondary dialog-done" onClick={() => setDetailsField(null)}>Done</button>
          </section>
        </div>
      )}
    </div>
  )
}

export default App
