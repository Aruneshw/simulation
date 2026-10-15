import { RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { IssueList, IssueSummary, Panel } from '../components/ui'
import { useStore } from '../store'
import type { Issue } from '../types'

interface Report { id: string; stage: string; summary: Record<string, number | boolean>; created_at: string; issues: Issue[] }

export default function ValidationWorkspace() {
  const { project, issues, validate, validatedAt } = useStore()
  const [stage, setStage] = useState('pre_simulation')
  const [domain, setDomain] = useState('')
  const [history, setHistory] = useState<Report[]>([])
  const [shown, setShown] = useState<Issue[] | null>(null)
  const loadHistory = () => project?.id && api.get<Report[]>(`/api/projects/${project.id}/validation-reports`).then(setHistory)
  useEffect(() => { loadHistory() }, [validatedAt]) // eslint-disable-line react-hooks/exhaustive-deps
  const list = shown ?? issues
  const domains = useMemo(() => [...new Set(list.map((i) => i.domain))], [list])
  const filtered = domain ? list.filter((i) => i.domain === domain) : list

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 12 }}>
        <div><h1>Automated design validation</h1>
          <div className="muted">Runs before every simulation and export: robot model, electrical compatibility, power, digital-twin bindings, firmware, world and scenario.</div></div>
        <span className="spacer" />
        <select value={stage} onChange={(e) => setStage(e.target.value)}><option value="pre_simulation">Pre-simulation</option><option value="pre_export">Pre-export</option></select>
        <button className="btn primary" onClick={() => { setShown(null); validate(stage) }}><RefreshCw size={14} />Run validation</button>
      </div>
      <div className="grid" style={{ gridTemplateColumns: '1fr 300px', alignItems: 'start' }}>
        <Panel title={<span className="row">Findings <IssueSummary issues={list} /></span>} actions={
          <select value={domain} onChange={(e) => setDomain(e.target.value)}><option value="">All domains</option>{domains.map((d) => <option key={d}>{d}</option>)}</select>}>
          <IssueList issues={filtered} empty="No issues — the design passes all automated checks." />
        </Panel>
        <Panel title="Validation reports" bodyClass="">
          <table className="t"><tbody>{history.map((h) => (
            <tr key={h.id} className="click" onClick={() => setShown(h.issues)}>
              <td className="xs">{new Date(h.created_at).toLocaleString()}<div className="muted">{h.stage}</div></td>
              <td><span className={`badge ${h.summary.passed ? 'good' : 'error'}`}>{h.summary.passed ? 'passed' : `${h.summary.critical}C ${h.summary.error}E`}</span>
                <div className="xs muted">{h.summary.warning} warn</div></td></tr>))}</tbody></table>
        </Panel>
      </div>
    </div>
  )
}
