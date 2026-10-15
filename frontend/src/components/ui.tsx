import { AlertOctagon, AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { useStore } from '../store'
import type { Issue } from '../types'

export function Panel({ title, actions, children, className, bodyClass, style }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; style?: React.CSSProperties
}) {
  return (
    <section className={`panel ${className ?? ''}`} style={style}>
      {(title || actions) && (
        <div className="panel-h"><h2>{title}</h2><div className="spacer" />{actions}</div>
      )}
      <div className={bodyClass ?? 'panel-b'}>{children}</div>
    </section>
  )
}

export function Num({ value, onChange, step = 0.01, min, max, unit, width }: {
  value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number; unit?: string; width?: number
}) {
  return (
    <span className="row" style={{ gap: 4 }}>
      <input type="number" value={Number.isFinite(value) ? +value.toFixed(6) : 0} step={step} min={min} max={max}
        style={width ? { width } : undefined}
        onChange={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v)) onChange(v) }} />
      {unit && <span className="muted xs">{unit}</span>}
    </span>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="field" title={hint}><span>{label}</span>{children}</label>
}

const STATUS_LABEL: Record<string, [string, string]> = {
  fully_modeled: ['Fully modeled', 'good'],
  simulation_supported: ['Simulation supported', 'good'],
  behavioral: ['Behavioral model', 'info'],
  cad_only: ['CAD only', ''],
  schematic_only: ['Schematic only', ''],
  imported_unverified: ['Imported · unverified', 'warning'],
  user_defined: ['User-defined', 'warning'],
}

const SHORT: Record<string, string> = {
  fully_modeled: 'full model', simulation_supported: 'sim', behavioral: 'behavioral', cad_only: 'CAD', schematic_only: 'schematic',
  imported_unverified: 'unverified', user_defined: 'user',
}

export function SupportBadge({ status, compact }: { status: string; compact?: boolean }) {
  const [label, cls] = STATUS_LABEL[status] ?? [status, '']
  return <span className={`badge ${cls}`} title={label}>{compact ? SHORT[status] ?? label : label}</span>
}

export const SEVERITY_ICON = {
  critical: <AlertOctagon size={14} color="var(--critical)" />,
  error: <XCircle size={14} color="var(--serious)" />,
  warning: <AlertTriangle size={14} color="var(--warning)" />,
  info: <Info size={14} color="var(--info)" />,
}

export function SeverityBadge({ s }: { s: Issue['severity'] }) {
  return <span className={`badge ${s}`}>{SEVERITY_ICON[s]}{s}</span>
}

export function IssueCard({ issue, compact }: { issue: Issue; compact?: boolean }) {
  const select = useStore((s) => s.select)
  return (
    <div className={`issue ${issue.severity}`} onClick={() => select(issue.refs)} role="button" tabIndex={0}>
      <div className="row" style={{ gap: 6 }}>
        {SEVERITY_ICON[issue.severity]}
        <strong>{issue.title}</strong>
        <span className="spacer" />
        <span className="chip">{issue.domain}</span>
        <span className="muted xs mono">{issue.code}</span>
      </div>
      {issue.connection && <div style={{ marginTop: 4 }}><span className="conn">{issue.connection}</span></div>}
      <div className="secondary small" style={{ marginTop: 4 }}>{issue.message}</div>
      {!compact && issue.specs.length > 0 && (
        <div className="xs muted" style={{ marginTop: 4 }}>
          {issue.specs.map((s, i) => (
            <div key={i}>
              {s.component} · {s.field} = <span className="mono">{String(s.value ?? '?')}{s.unit && ` ${s.unit}`}</span>{' '}
              <span className={`badge ${s.source === 'datasheet' ? 'good' : s.source === 'assumption' ? 'warning' : ''}`}>{s.source}</span>
              {s.url && <> · <a href={s.url} target="_blank" rel="noreferrer">source ↗</a></>}
            </div>
          ))}
        </div>
      )}
      {issue.fix && <div className="small fix" style={{ marginTop: 4 }}>Fix: {issue.fix}</div>}
    </div>
  )
}

export function IssueList({ issues, empty = 'No issues found.', compact }: { issues: Issue[]; empty?: string; compact?: boolean }) {
  if (!issues.length) return <div className="row muted" style={{ padding: 8 }}><CheckCircle2 size={16} color="var(--good)" />{empty}</div>
  return <div className="col">{issues.map((i, k) => <IssueCard key={k} issue={i} compact={compact} />)}</div>
}

export function IssueSummary({ issues }: { issues: Issue[] }) {
  const c = (s: string) => issues.filter((i) => i.severity === s).length
  return (
    <span className="row" style={{ gap: 4 }}>
      {(['critical', 'error', 'warning', 'info'] as const).map((s) => c(s) > 0 && <span key={s} className={`badge ${s}`}>{SEVERITY_ICON[s]}{c(s)}</span>)}
      {c('critical') + c('error') === 0 && <span className="badge good"><CheckCircle2 size={12} />design OK</span>}
    </span>
  )
}

export function Kpi({ label, value, unit, note }: { label: string; value: ReactNode; unit?: string; note?: string }) {
  return (
    <div className="panel kpi" title={note}>
      <div className="v">{value}{unit && <span className="muted" style={{ fontSize: 13, marginLeft: 3 }}>{unit}</span>}</div>
      <div className="l">{label}</div>
    </div>
  )
}

export function fmt(v: unknown, d = 2): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return Number.isFinite(v) ? v.toFixed(d) : '∞'
  return String(v)
}
