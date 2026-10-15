import { CheckCircle2, CircleDashed, FolderOpen, Plus, Trash2, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmt, Panel } from '../components/ui'
import { useStore } from '../store'

interface ProjectRow { id: string; name: string; type: string; updated_at: string; description: string }
interface System {
  version: string
  resources: { python: string; platform: string; cpu_count: number; cpu_percent?: number; memory_total_gb?: number; memory_used_percent?: number; disk_free_gb?: number; compute: { gpu: string[] | null; cuda: boolean } }
  tools: Record<string, { available: boolean; used_for: string; license: string; install: string; version?: string | null }>
  library: { total: number; by_status: Record<string, number>; library_version: string }
}
interface RunRow { run_id: string; project: string | null; project_id: string; status: string; metrics: Record<string, unknown>; created_at: string }

const TYPES = ['amr', 'agv', 'robotic_arm', 'drone', 'gripper', 'industrial_automation', 'iot', 'motor_control', 'embedded', 'custom']

export default function Dashboard() {
  const { open, toast, setWorkspace } = useStore()
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [sys, setSys] = useState<System | null>(null)
  const [templates, setTemplates] = useState<{ projects: { id: string; name: string }[]; worlds: string[] } | null>(null)
  const [runs, setRuns] = useState<RunRow[]>([])
  const [name, setName] = useState('New robot')
  const [type, setType] = useState('amr')
  const [world, setWorld] = useState('warehouse')

  const refresh = () => {
    api.get<ProjectRow[]>('/api/projects').then(setProjects).catch(() => undefined)
    api.get<RunRow[]>('/api/simulations').then(setRuns).catch(() => undefined)
  }
  useEffect(() => {
    refresh()
    api.get<System>('/api/system').then(setSys).catch((e) => toast('error', `Backend unreachable: ${e.message}`))
    api.get<typeof templates>('/api/templates').then(setTemplates).catch(() => undefined)
  }, [toast])

  const create = async (template?: string) => {
    const p = await api.post<{ id: string }>('/api/projects', { name: template ? '' : name, type, template, world_template: template ? null : world })
    await open(p.id)
    toast('ok', 'Project created')
  }
  const importPkg = async (f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    try {
      const r = await api.post<{ project_id: string; report: { errors: string[]; warnings: string[] } }>('/api/import/package', fd)
      if (r.report.errors.length) toast('error', `Imported with ${r.report.errors.length} integrity errors: ${r.report.errors[0]}`)
      await open(r.project_id)
    } catch (e) { toast('error', (e as Error).message) }
  }

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 14 }}>
        <div>
          <h1>RoboVerse Studio</h1>
          <div className="muted">Design. Connect. Simulate. Validate. Build. {sys && <span className="xs">v{sys.version}</span>}</div>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(320px, 1.1fr) minmax(320px, 1fr)', alignItems: 'start' }}>
        <div className="grid">
          <Panel title="Create a project">
            <div className="fields">
              <label className="field"><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} /></label>
              <label className="field"><span>Project type</span>
                <select value={type} onChange={(e) => setType(e.target.value)}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></label>
              <label className="field"><span>Environment</span>
                <select value={world} onChange={(e) => setWorld(e.target.value)}>{templates?.worlds.map((w) => <option key={w}>{w}</option>)}</select></label>
              <div className="row"><button className="btn primary" onClick={() => create()}><Plus size={14} />Create blank project</button>
                <label className="btn"><Upload size={14} />Import .rvproj
                  <input type="file" accept=".rvproj,.zip" hidden onChange={(e) => e.target.files?.[0] && importPkg(e.target.files[0])} /></label>
              </div>
            </div>
            <hr className="sep" />
            <h4 style={{ marginBottom: 8 }}>Sample projects (complete digital twins)</h4>
            <div className="col">
              {templates?.projects.map((t) => (
                <div key={t.id} className="row panel" style={{ padding: 10 }}>
                  <div><strong>{t.name}</strong></div>
                  <span className="spacer" />
                  <button className="btn sm" onClick={() => create(t.id)}>Open sample</button>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Recent projects" bodyClass="">
            {projects.length === 0 ? <div className="empty">No projects yet — create one or open a sample.</div> : (
              <table className="t">
                <thead><tr><th>Name</th><th>Type</th><th>Updated</th><th /></tr></thead>
                <tbody>{projects.map((p) => (
                  <tr key={p.id} className="click" onClick={() => open(p.id)}>
                    <td><strong>{p.name}</strong><div className="muted xs">{p.description.slice(0, 90)}</div></td>
                    <td><span className="chip">{p.type}</span></td>
                    <td className="muted xs">{new Date(p.updated_at).toLocaleString()}</td>
                    <td className="row" style={{ justifyContent: 'flex-end' }}>
                      <button className="btn sm"><FolderOpen size={13} />Open</button>
                      <button className="btn sm icon ghost" title="Delete" onClick={async (e) => {
                        e.stopPropagation()
                        if (!confirm(`Delete "${p.name}" and its simulation history?`)) return
                        await api.del(`/api/projects/${p.id}`); refresh()
                      }}><Trash2 size={13} /></button>
                    </td>
                  </tr>))}</tbody>
              </table>)}
          </Panel>
          <Panel title="Simulation history" bodyClass="">
            {runs.length === 0 ? <div className="empty">No simulation runs yet.</div> : (
              <table className="t">
                <thead><tr><th>Project</th><th>Status</th><th className="num">Goals</th><th className="num">Collisions</th><th className="num">Distance</th><th>When</th></tr></thead>
                <tbody>{runs.slice(0, 12).map((r) => (
                  <tr key={r.run_id} className="click" onClick={() => open(r.project_id)}>
                    <td>{r.project ?? r.project_id}</td>
                    <td><span className={`badge ${r.status === 'completed' ? 'good' : r.status === 'error' ? 'critical' : ''}`}>{r.status}</span>
                      {r.metrics?.success === true && <span className="badge good" style={{ marginLeft: 4 }}>success</span>}</td>
                    <td className="num">{fmt(r.metrics?.goals_reached, 0)}/{fmt(r.metrics?.goals_total, 0)}</td>
                    <td className="num">{fmt(r.metrics?.collisions, 0)}</td>
                    <td className="num">{fmt(r.metrics?.distance_m, 1)} m</td>
                    <td className="muted xs">{new Date(r.created_at).toLocaleString()}</td>
                  </tr>))}</tbody>
              </table>)}
          </Panel>
        </div>
        <div className="grid">
          <Panel title="Component library" actions={<button className="btn sm" onClick={() => setWorkspace('library')}>Browse</button>}>
            {sys && (
              <>
                <div className="row" style={{ marginBottom: 8 }}><span style={{ fontSize: 22, fontWeight: 650 }}>{sys.library.total}</span><span className="muted">components · library {sys.library.library_version}</span></div>
                <table className="t"><tbody>
                  {Object.entries(sys.library.by_status).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                    <tr key={k}><td>{k.replace(/_/g, ' ')}</td><td className="num">{v}</td></tr>))}
                </tbody></table>
                <div className="xs muted" style={{ marginTop: 6 }}>Support status is tracked per part: only "fully modeled" parts are solved from first principles.</div>
              </>)}
          </Panel>
          <Panel title="Integrations & dependency health" bodyClass="">
            <table className="t"><thead><tr><th>Tool</th><th>Status</th><th>Used for</th></tr></thead>
              <tbody>{sys && Object.entries(sys.tools).map(([k, t]) => (
                <tr key={k} title={`License: ${t.license}\nInstall: ${t.install}`}>
                  <td><strong>{k}</strong>{t.version && <div className="muted xs">{t.version}</div>}</td>
                  <td>{t.available ? <span className="badge good"><CheckCircle2 size={11} />installed</span> : <span className="badge"><CircleDashed size={11} />not installed</span>}</td>
                  <td className="secondary xs">{t.used_for}{!t.available && <div className="muted">{t.install}</div>}</td>
                </tr>))}</tbody></table>
          </Panel>
          <Panel title="Resources">
            {sys && (
              <div className="fields small">
                <div className="row"><span className="muted" style={{ width: 120 }}>Platform</span>{sys.resources.platform}</div>
                <div className="row"><span className="muted" style={{ width: 120 }}>CPU</span>{sys.resources.cpu_count} cores · {fmt(sys.resources.cpu_percent, 0)}% busy</div>
                <div className="row"><span className="muted" style={{ width: 120 }}>Memory</span>{fmt(sys.resources.memory_total_gb, 1)} GB · {fmt(sys.resources.memory_used_percent, 0)}% used</div>
                <div className="row"><span className="muted" style={{ width: 120 }}>Disk free</span>{fmt(sys.resources.disk_free_gb, 1)} GB</div>
                <div className="row"><span className="muted" style={{ width: 120 }}>GPU</span>{sys.resources.compute.gpu ? sys.resources.compute.gpu.join(', ') : 'none detected (CPU-only paths are used)'}</div>
              </div>)}
          </Panel>
        </div>
      </div>
    </div>
  )
}
