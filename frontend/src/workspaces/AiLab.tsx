import { Cpu } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmt, Panel } from '../components/ui'
import { useStore } from '../store'

interface Caps { cpu_count: number; gpu: string[] | null; cuda: boolean; opencv: boolean; open3d: boolean; torch: boolean }
interface Run { run_id: string; status: string; metrics: Record<string, unknown>; created_at: string }

export default function AiLab() {
  const { project } = useStore()
  const [caps, setCaps] = useState<Caps | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [anom, setAnom] = useState<{ anomalies: { t: number; value: number }[]; method: string; label: string } | null>(null)
  const [signal, setSignal] = useState('bus_i')
  useEffect(() => {
    api.get<Caps>('/api/ai/capabilities').then(setCaps)
    if (project?.id) api.get<Run[]>(`/api/projects/${project.id}/simulations`).then(setRuns)
  }, [project?.id])
  const latest = runs.find((r) => (r.metrics as { perception?: unknown }).perception)
  const p = latest?.metrics.perception as Record<string, number> | undefined

  return (
    <div className="page">
      <h1>AI & perception lab</h1>
      <div className="muted" style={{ marginBottom: 12 }}>Perception modules consume simulated sensor data. Their outputs are scored against simulator ground truth and are never fed back as truth.</div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', alignItems: 'start' }}>
        <Panel title={<span className="row"><Cpu size={14} />Compute capabilities</span>}>
          {caps && (
            <table className="t"><tbody>
              <tr><td>CPU cores</td><td>{caps.cpu_count}</td></tr>
              <tr><td>GPU</td><td>{caps.gpu ? caps.gpu.join(', ') : <span className="muted">none detected — CPU paths only</span>}</td></tr>
              <tr><td>CUDA</td><td>{caps.cuda ? 'yes' : 'no'}</td></tr>
              {(['opencv', 'open3d', 'torch'] as const).map((k) => <tr key={k}><td>{k}</td><td>{caps[k] ? <span className="badge good">installed</span> : <span className="badge">not installed</span>}</td></tr>)}
            </tbody></table>)}
        </Panel>
        <Panel title="LiDAR obstacle detection (built-in, CPU)">
          <div className="small secondary">Euclidean clustering of each scan at the <em>estimated</em> pose. Detections are matched to ground-truth obstacles within sensor range to report precision, recall and position error.</div>
          {p ? (
            <table className="t" style={{ marginTop: 8 }}><tbody>
              <tr><td>Mean precision</td><td className="num">{fmt(p.mean_precision, 3)}</td></tr>
              <tr><td>Mean recall</td><td className="num">{fmt(p.mean_recall, 3)}</td></tr>
              <tr><td>Mean position error</td><td className="num">{fmt(p.mean_position_error_m, 3)} m</td></tr>
              <tr><td>Frames scored</td><td className="num">{p.frames}</td></tr>
            </tbody></table>) : <div className="empty">Run a simulation with a LiDAR to score perception.</div>}
          <div className="xs muted">Precision is limited by walls/racks being split into several clusters; this is a measurable property of the detector, not of the simulator.</div>
        </Panel>
        <Panel title="Telemetry anomaly detection">
          <div className="small secondary">Trailing-window z-score over a telemetry signal of a live session (e.g. stall-current spikes, collisions).</div>
          <div className="row" style={{ marginTop: 8 }}>
            <select value={signal} onChange={(e) => setSignal(e.target.value)}>{['bus_i', 'v', 'loc_err', 'left_wheel_i', 'right_wheel_i'].map((s) => <option key={s}>{s}</option>)}</select>
            <select id="runsel" defaultValue="">{runs.map((r) => <option key={r.run_id} value={r.run_id}>{new Date(r.created_at).toLocaleTimeString()} · {r.status}</option>)}</select>
            <button className="btn sm" onClick={async () => {
              const id = (document.getElementById('runsel') as HTMLSelectElement).value || runs[0]?.run_id
              if (id) setAnom(await api.get<NonNullable<typeof anom>>(`/api/simulations/${id}/anomalies`, { signal }).catch(() => ({ anomalies: [], method: 'session not in memory (restart clears live sessions)', label: '' })))
            }}>Detect</button>
          </div>
          {anom && (
            <div style={{ marginTop: 8 }}>
              <div className="xs muted">{anom.method} · {anom.label}</div>
              {anom.anomalies.length === 0 ? <div className="small">No anomalies.</div> : anom.anomalies.slice(0, 20).map((a) => <div key={a.t} className="small mono">t={a.t.toFixed(2)} s · {a.value.toFixed(3)}</div>)}
            </div>)}
        </Panel>
        <Panel title="Optional modules">
          <div className="small secondary">Camera-based detection, segmentation and visual tracking plug in as perception subsystems with the same contract (inputs: simulated sensor frames; outputs: detections scored against ground truth). They require OpenCV / Open3D / a model runtime, which are detected above and are not assumed to be present.</div>
        </Panel>
      </div>
    </div>
  )
}
