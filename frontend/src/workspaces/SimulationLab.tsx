import { Grid, OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { CircleStop, Download, MapPin, Octagon, Pause, Play, RotateCcw, Square, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { ApiError, api, wsUrl } from '../api'
import { LineChart } from '../components/LineChart'
import { RobotModel, WorldObjectMesh, ZUP } from '../components/scene'
import { Field, fmt, IssueList, Num, Panel } from '../components/ui'
import { useStore } from '../store'
import type { Issue, Project, WorldObject } from '../types'

type Row = Record<string, number | string | boolean | null>
interface SimEvent { t: number; kind: string; severity: string; message: string }
interface Frame { type: 'frame'; t: number; row: Row; scan?: [number, number, number][]; path?: [number, number][] | null; dynamic?: { id: string; x: number; y: number; r: number }[]; events: SimEvent[]; detections?: { x: number; y: number }[] }
interface InitReport {
  strategy: string; macro_dt: number; backend: string; backend_fidelity: string; base_load_w: number
  sequence: { name: string; rate_hz: number; fidelity: string }[]
  contract: { signal: string; from: string; to: string; coupling: string }[]
  missing_inputs: string[]; result_labels: Record<string, string>
}

const MAX_ROWS = 6000

export default function SimulationLab() {
  const { project, edit, toast } = useStore()
  const sim = project!.simulation
  const [runId, setRunId] = useState<string | null>(null)
  const [status, setStatus] = useState('idle')
  const [init, setInit] = useState<InitReport | null>(null)
  const [blocked, setBlocked] = useState<Issue[] | null>(null)
  const [estop, setEstop] = useState(false)
  const [speed, setSpeed] = useState(sim.real_time_factor)
  const [view, setView] = useState<'2d' | '3d'>('2d')
  const [addWp, setAddWp] = useState(false)
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null)
  const [tick, setTick] = useState(0)
  const rows = useRef<Row[]>([])
  const events = useRef<SimEvent[]>([])
  const last = useRef<Frame | null>(null)
  const trail = useRef<[number, number][]>([])
  const etrail = useRef<[number, number][]>([])
  const ws = useRef<WebSocket | null>(null)
  const wall0 = useRef(0)
  const raf = useRef(0)

  const bump = useCallback(() => {
    if (raf.current) return
    raf.current = requestAnimationFrame(() => { raf.current = 0; setTick((t) => t + 1) })
  }, [])

  useEffect(() => () => { ws.current?.close() }, [])

  const connect = (id: string) => {
    ws.current?.close()
    const s = new WebSocket(wsUrl(`/ws/simulations/${id}`))
    ws.current = s
    s.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.type === 'frame') {
        const f = m as Frame
        last.current = f
        rows.current.push(f.row)
        if (rows.current.length > MAX_ROWS) rows.current.splice(0, rows.current.length - MAX_ROWS)
        trail.current.push([Number(f.row.x), Number(f.row.y)])
        etrail.current.push([Number(f.row.est_x), Number(f.row.est_y)])
        if (f.events.length) events.current.push(...f.events)
        bump()
      } else if (m.type === 'status') {
        setStatus(m.status)
        if (m.init) setInit(m.init)
      } else if (m.type === 'hello') {
        setStatus(m.status); setInit(m.init)
      } else if (m.type === 'finished') {
        setStatus(m.status)
        setMetrics(m.result?.metrics ?? null)
        if (m.error) toast('error', m.error)
      }
    }
    s.onerror = () => toast('error', 'Telemetry connection lost')
  }

  const reset = () => {
    rows.current = []; events.current = []; trail.current = []; etrail.current = []; last.current = null
    setMetrics(null); setEstop(false); setTick((t) => t + 1)
  }

  const start = async (force = false) => {
    reset()
    setBlocked(null)
    try {
      const r = await api.post<{ run_id: string; init: InitReport }>('/api/simulations', { project, force })
      setRunId(r.run_id); setInit(r.init)
      connect(r.run_id)
      await new Promise((res) => setTimeout(res, 150))
      await api.post(`/api/simulations/${r.run_id}/control`, { action: 'speed', value: speed })
      await api.post(`/api/simulations/${r.run_id}/control`, { action: 'start' })
      wall0.current = performance.now()
      setStatus('running')
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const body = e.body as { validation: { issues: Issue[] } }
        setBlocked(body.validation.issues.filter((i) => i.severity === 'critical' || i.severity === 'error'))
      } else toast('error', (e as Error).message)
    }
  }
  const control = (action: string, value?: unknown) => runId && api.post(`/api/simulations/${runId}/control`, { action, value }).catch((e) => toast('error', e.message))

  // teleop keyboard
  useEffect(() => {
    if (sim.scenario.mode !== 'teleop' || !runId) return
    const keys = new Set<string>()
    const send = () => {
      const v = (keys.has('ArrowUp') ? 0.4 : 0) - (keys.has('ArrowDown') ? 0.3 : 0)
      const w = (keys.has('ArrowLeft') ? 1.0 : 0) - (keys.has('ArrowRight') ? 1.0 : 0)
      control('teleop', { v, w })
    }
    const d = (e: KeyboardEvent) => { if (e.key.startsWith('Arrow')) { e.preventDefault(); keys.add(e.key); send() } }
    const u = (e: KeyboardEvent) => { if (e.key.startsWith('Arrow')) { keys.delete(e.key); send() } }
    window.addEventListener('keydown', d); window.addEventListener('keyup', u)
    return () => { window.removeEventListener('keydown', d); window.removeEventListener('keyup', u) }
  }, [sim.scenario.mode, runId]) // eslint-disable-line react-hooks/exhaustive-deps

  const f = last.current
  const r = f?.row
  const running = status === 'running' || status === 'paused'
  const charts = useMemo(() => {
    const rs = rows.current
    const t = rs.map((x) => Number(x.t))
    const col = (k: string) => rs.map((x) => (x[k] == null ? null : Number(x[k])))
    const motors = rs.length ? Object.keys(rs[rs.length - 1]).filter((k) => k.endsWith('_rpm')).map((k) => k.replace('_rpm', '')) : []
    return { t, col, motors }
  }, [tick]) // eslint-disable-line react-hooks/exhaustive-deps
  void tick

  const S1 = 'var(--series-1)', S2 = 'var(--series-2)'

  return (
    <div className="split" style={{ gridTemplateColumns: '300px 1fr 400px' }}>
      <aside className="scroll" style={{ borderRight: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <div className="col">
          <Panel title="Scenario">
            <div className="fields">
              <Field label="Mode"><select value={sim.scenario.mode} onChange={(e) => edit((p) => { p.simulation.scenario.mode = e.target.value as typeof sim.scenario.mode })}>
                <option value="waypoints">Waypoint following</option><option value="goal">Goal navigation</option>
                <option value="dock">Return to dock</option><option value="teleop">Teleop (arrow keys)</option><option value="open_loop">Open-loop command</option></select></Field>
              {(sim.scenario.mode === 'waypoints' || sim.scenario.mode === 'goal') && (
                <div className="col" style={{ gap: 4 }}>
                  {(sim.scenario.mode === 'goal' ? (sim.scenario.goal ? [sim.scenario.goal] : []) : sim.scenario.waypoints).map((w, i) => (
                    <div key={i} className="row">
                      <span className="xs muted" style={{ width: 34 }}>{sim.scenario.mode === 'goal' ? 'Goal' : `WP${i + 1}`}</span>
                      <Num value={w[0]} step={0.1} width={70} onChange={(v) => edit((p) => { const L = p.simulation.scenario.mode === 'goal' ? [p.simulation.scenario.goal!] : p.simulation.scenario.waypoints; L[i][0] = v }, { merge: true })} />
                      <Num value={w[1]} step={0.1} width={70} onChange={(v) => edit((p) => { const L = p.simulation.scenario.mode === 'goal' ? [p.simulation.scenario.goal!] : p.simulation.scenario.waypoints; L[i][1] = v }, { merge: true })} />
                      <button className="btn sm icon ghost" onClick={() => edit((p) => { if (p.simulation.scenario.mode === 'goal') p.simulation.scenario.goal = null; else p.simulation.scenario.waypoints.splice(i, 1) })}><Trash2 size={12} /></button>
                    </div>))}
                  <button className={`btn sm ${addWp ? 'active' : ''}`} onClick={() => setAddWp(!addWp)}><MapPin size={13} />{addWp ? 'Click the map to place…' : 'Place on map'}</button>
                </div>)}
              <Field label="Return to dock"><input type="checkbox" checked={sim.scenario.return_to_dock} onChange={(e) => edit((p) => { p.simulation.scenario.return_to_dock = e.target.checked })} /></Field>
              {sim.scenario.mode === 'open_loop' && <>
                <Field label="v cmd"><Num value={sim.scenario.open_loop_cmd[0]} step={0.05} unit="m/s" onChange={(v) => edit((p) => { p.simulation.scenario.open_loop_cmd[0] = v }, { merge: true })} /></Field>
                <Field label="ω cmd"><Num value={sim.scenario.open_loop_cmd[1]} step={0.1} unit="rad/s" onChange={(v) => edit((p) => { p.simulation.scenario.open_loop_cmd[1] = v }, { merge: true })} /></Field></>}
              <Field label="Scripted E-stop" hint="Seconds into the run; empty = none"><Num value={sim.scenario.estop_at ?? 0} step={1} unit="s" onChange={(v) => edit((p) => { p.simulation.scenario.estop_at = v > 0 ? v : null }, { merge: true })} /></Field>
            </div>
          </Panel>
          <Panel title="Engine & timing">
            <div className="fields">
              <Field label="Physics backend"><select value={sim.physics_backend} onChange={(e) => edit((p) => { p.simulation.physics_backend = e.target.value as typeof sim.physics_backend })}>
                <option value="builtin_planar">Built-in planar dynamics</option><option value="mujoco">MuJoCo (3D contacts)</option></select></Field>
              <Field label="Fixed timestep"><Num value={sim.dt * 1000} step={1} unit="ms" onChange={(v) => edit((p) => { p.simulation.dt = v / 1000 }, { merge: true })} /></Field>
              <Field label="Max duration"><Num value={sim.duration} step={10} unit="s" onChange={(v) => edit((p) => { p.simulation.duration = v }, { merge: true })} /></Field>
              <Field label="Random seed"><Num value={sim.seed} step={1} onChange={(v) => edit((p) => { p.simulation.seed = Math.round(v) }, { merge: true })} /></Field>
              <Field label="Sensor noise"><input type="checkbox" checked={sim.sensor_noise} onChange={(e) => edit((p) => { p.simulation.sensor_noise = e.target.checked })} /></Field>
              <Field label="LiDAR map matching"><input type="checkbox" checked={sim.localization_scan_matching} onChange={(e) => edit((p) => { p.simulation.localization_scan_matching = e.target.checked })} /></Field>
              <Field label="Comm latency"><Num value={sim.comm_latency_ms} step={5} unit="ms" onChange={(v) => edit((p) => { p.simulation.comm_latency_ms = v }, { merge: true })} /></Field>
              <Field label="Ambient"><Num value={sim.ambient_c} step={1} unit="°C" onChange={(v) => edit((p) => { p.simulation.ambient_c = v }, { merge: true })} /></Field>
            </div>
            <p className="xs muted">Configuration + seed make every run reproducible. The full configuration is stored with each run.</p>
          </Panel>
          {init && (
            <Panel title="Co-simulation plan">
              <div className="xs secondary">{init.strategy}; macro step {init.macro_dt * 1000} ms; backend <strong>{init.backend}</strong> — {init.backend_fidelity}.</div>
              <table className="t" style={{ marginTop: 6 }}><thead><tr><th>#</th><th>Subsystem</th><th className="num">Hz</th></tr></thead>
                <tbody>{init.sequence.map((s, i) => <tr key={s.name} title={s.fidelity}><td className="muted">{i + 1}</td><td>{s.name}<div className="xs muted">{s.fidelity}</div></td><td className="num">{s.rate_hz}</td></tr>)}</tbody></table>
              <details style={{ marginTop: 6 }}><summary className="xs">Data-exchange contract ({init.contract.length} edges, {init.contract.filter((c) => c.coupling !== 'same_step').length} with one-step delay)</summary>
                <table className="t"><tbody>{init.contract.map((c, i) => <tr key={i}><td className="mono xs">{c.signal}</td><td className="xs">{c.from} → {c.to}</td><td className="xs muted">{c.coupling}</td></tr>)}</tbody></table></details>
            </Panel>)}
        </div>
      </aside>

      <div className="viewport">
        <div className="overlay toolbar" style={{ top: 10, left: 10 }}>
          {!running
            ? <button className="btn primary" onClick={() => start()}><Play size={14} />Run simulation</button>
            : status === 'paused'
              ? <button className="btn primary" onClick={() => control('resume')}><Play size={14} />Resume</button>
              : <button className="btn" onClick={() => control('pause')}><Pause size={14} />Pause</button>}
          <button className="btn" disabled={!running} onClick={() => control('stop')}><Square size={14} />Stop</button>
          <button className="btn" disabled={!runId} onClick={() => { reset(); control('reset'); setTimeout(() => runId && connect(runId), 200) }}><RotateCcw size={14} />Reset</button>
          <select value={speed} onChange={(e) => { const v = parseFloat(e.target.value); setSpeed(v); control('speed', v) }} title="Simulation speed (× real time)">
            {[0.5, 1, 2, 5, 10, 0].map((v) => <option key={v} value={v}>{v === 0 ? 'max speed' : `${v}× real time`}</option>)}</select>
          <button className={`btn ${estop ? 'danger' : ''}`} disabled={!running} onClick={() => { setEstop(!estop); control('estop', !estop) }}
            title="Emergency stop (simulated — not a certified safety function)"><Octagon size={14} />{estop ? 'E-STOP ACTIVE' : 'E-stop'}</button>
        </div>
        <div className="overlay toolbar" style={{ top: 10, right: 10 }}>
          <button className={`btn sm ${view === '2d' ? 'active' : ''}`} onClick={() => setView('2d')}>2D map</button>
          <button className={`btn sm ${view === '3d' ? 'active' : ''}`} onClick={() => setView('3d')}>3D</button>
        </div>
        {sim.scenario.mode === 'teleop' && running && <div className="overlay panel xs" style={{ bottom: 10, left: 10, padding: 6 }}>Teleop: hold arrow keys to drive</div>}
        <div className="overlay legend panel" style={{ bottom: 10, right: 10, padding: '5px 8px' }}>
          <span><span className="swatch" style={{ background: '#22c55e' }} />ground truth</span>
          <span><span className="swatch" style={{ background: '#a78bfa' }} />estimate (odom+IMU+scan match)</span>
          <span><span className="swatch" style={{ background: '#ff4d6d' }} />LiDAR hits</span>
          <span><span className="swatch" style={{ background: '#facc15' }} />planned path</span>
        </div>
        {view === '2d'
          ? <MapView project={project!} frame={f} trail={trail.current} etrail={etrail.current} tick={tick} addWp={addWp}
              onAdd={(x, y) => edit((p) => { if (p.simulation.scenario.mode === 'goal') p.simulation.scenario.goal = [x, y]; else p.simulation.scenario.waypoints.push([x, y]) })} />
          : <Live3D project={project!} frame={f} />}
        {blocked && (
          <div className="overlay panel" style={{ top: 60, left: 10, right: 10, maxHeight: '70%', overflow: 'auto', padding: 12 }}>
            <div className="row"><CircleStop size={16} color="var(--critical)" /><strong>Pre-simulation validation found {blocked.length} blocking issue(s)</strong><span className="spacer" />
              <button className="btn sm" onClick={() => setBlocked(null)}>Close</button>
              <button className="btn sm danger" onClick={() => start(true)}>Run anyway</button></div>
            <div style={{ marginTop: 8 }}><IssueList issues={blocked} /></div>
          </div>)}
      </div>

      <aside className="scroll" style={{ borderLeft: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
          <Tile label="Sim time" v={`${fmt(r?.t, 1)} s`} sub={running ? `wall ${((performance.now() - wall0.current) / 1000).toFixed(1)} s` : status} />
          <Tile label="Mission" v={String(r?.mission ?? '—')} sub={String(r?.nav ?? '')} />
          <Tile label="Speed" v={`${fmt(r?.v, 2)} m/s`} sub={`yaw ${fmt(r?.w, 2)} rad/s`} />
          <Tile label="Battery" v={`${fmt(r?.bus_v, 2)} V`} sub={r?.soc != null ? `SoC ${(Number(r.soc) * 100).toFixed(2)} %` : ''} />
          <Tile label="Bus current" v={`${fmt(r?.bus_i, 2)} A`} sub="analytical model" />
          <Tile label="Collisions" v={String(r?.collisions ?? 0)} sub={`loc err ${fmt(r?.loc_err, 3)} m`} />
        </div>
        <div className="col" style={{ marginTop: 10, gap: 10 }}>
          <LineChart title="Linear velocity" unit="m/s" t={charts.t} series={[
            { key: 'cmd', label: 'cmd', color: S2, values: charts.col('cmd_v') },
            { key: 'v', label: 'actual', color: S1, values: charts.col('v') }]} />
          {charts.motors.length >= 2 && <>
            <LineChart title="Motor current" unit="A" t={charts.t} series={charts.motors.slice(0, 2).map((m, i) => ({ key: m, label: m.replace('_wheel', ''), color: i ? S2 : S1, values: charts.col(`${m}_i`) }))} />
            <LineChart title="Motor speed" unit="rpm" t={charts.t} digits={0} series={charts.motors.slice(0, 2).map((m, i) => ({ key: m, label: m.replace('_wheel', ''), color: i ? S2 : S1, values: charts.col(`${m}_rpm`) }))} />
            <LineChart title="Winding temperature (estimate)" unit="°C" t={charts.t} digits={1} series={charts.motors.slice(0, 2).map((m, i) => ({ key: m, label: m.replace('_wheel', ''), color: i ? S2 : S1, values: charts.col(`${m}_temp`) }))} />
          </>}
          <LineChart title="Battery terminal voltage" unit="V" t={charts.t} series={[{ key: 'bv', label: 'V', color: S1, values: charts.col('bus_v') }]} />
          <LineChart title="Battery current" unit="A" t={charts.t} series={[{ key: 'bi', label: 'A', color: S1, values: charts.col('bus_i') }]} />
          <LineChart title="Localization error |truth − estimate|" unit="m" t={charts.t} digits={3} yMin={0} series={[{ key: 'le', label: 'm', color: S1, values: charts.col('loc_err') }]} />
        </div>
        {metrics && <RunMetrics m={metrics} />}
        <Panel title={`Events (${events.current.length})`} style={{ marginTop: 10 }} bodyClass="">
          <div style={{ maxHeight: 220, overflow: 'auto' }}>
            <table className="t"><tbody>{[...events.current].reverse().map((e, i) => (
              <tr key={i}><td className="num xs mono">{e.t.toFixed(2)}</td><td><span className={`badge ${e.severity === 'critical' ? 'critical' : e.severity === 'error' ? 'error' : e.severity === 'warning' ? 'warning' : 'info'}`}>{e.kind}</span></td><td className="xs">{e.message}</td></tr>))}</tbody></table>
          </div>
        </Panel>
        {runId && <a className="btn sm" style={{ marginTop: 8 }} href={`/api/simulations/${runId}/telemetry.csv`}><Download size={13} />Telemetry CSV</a>}
      </aside>
    </div>
  )
}

function Tile({ label, v, sub }: { label: string; v: string; sub?: string }) {
  return <div className="panel" style={{ padding: '6px 8px' }}><div className="xs muted">{label}</div><div style={{ fontWeight: 650, fontVariantNumeric: 'tabular-nums' }}>{v}</div>{sub && <div className="xs muted">{sub}</div>}</div>
}

function RunMetrics({ m }: { m: Record<string, unknown> }) {
  const p = m.perception as Record<string, number> | undefined
  const rows: [string, unknown, string?][] = [
    ['Result', m.success ? 'success' : 'not successful'], ['Goals reached', `${m.goals_reached}/${m.goals_total}`],
    ['Distance travelled', `${fmt(m.distance_m, 2)} m`], ['Planned length', `${fmt(m.planned_length_m, 2)} m`],
    ['Path efficiency', fmt(m.path_efficiency, 3)], ['Collisions', m.collisions], ['Contact time', `${fmt(m.contact_time_s, 2)} s`],
    ['Min front clearance', `${fmt(m.min_front_clearance_m, 2)} m`], ['Localization RMSE', `${fmt(m.loc_rmse_m, 3)} m`],
    ['Energy used', `${fmt(m.energy_wh, 3)} Wh`, 'analytical'], ['Peak bus current', `${fmt(m.peak_bus_current_a, 2)} A`, 'analytical'],
    ['Max motor temp', `${fmt(m.max_motor_temp_c_estimate, 1)} °C`, 'estimate — not a safety rating'],
  ]
  return (
    <Panel title="Navigation performance" style={{ marginTop: 10 }} bodyClass="">
      <table className="t"><tbody>
        {rows.map(([k, v, n]) => <tr key={k}><td className="secondary">{k}</td><td className="num">{String(v)}</td><td className="xs muted">{n}</td></tr>)}
        {p && <tr><td className="secondary">Perception (vs ground truth)</td><td className="num">P {fmt(p.mean_precision, 2)} · R {fmt(p.mean_recall, 2)}</td><td className="xs muted">AI estimate</td></tr>}
      </tbody></table>
    </Panel>
  )
}

function MapView({ project, frame, trail, etrail, tick, addWp, onAdd }: {
  project: Project; frame: Frame | null; trail: [number, number][]; etrail: [number, number][]; tick: number; addWp: boolean; onAdd: (x: number, y: number) => void
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [x0, y0, x1, y1] = project.world.bounds
  const geom = useRef({ s: 1, ox: 0, oy: 0 })
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const dpr = window.devicePixelRatio || 1
    const W = c.clientWidth, H = c.clientHeight
    c.width = W * dpr; c.height = H * dpr
    const g = c.getContext('2d')!
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    const s = Math.min((W - 40) / (x1 - x0), (H - 40) / (y1 - y0))
    const ox = (W - s * (x1 - x0)) / 2 - s * x0, oy = (H + s * (y1 - y0)) / 2 + s * y0
    geom.current = { s, ox, oy }
    const P = (x: number, y: number): [number, number] => [ox + s * x, oy - s * y]
    const css = getComputedStyle(document.documentElement)
    g.fillStyle = css.getPropertyValue('--surface-2'); g.fillRect(0, 0, W, H)
    // grid (1 m)
    g.strokeStyle = css.getPropertyValue('--grid'); g.lineWidth = 1
    for (let x = Math.ceil(x0); x <= x1; x++) { const [a, b] = P(x, y0); const [, d] = P(x, y1); g.beginPath(); g.moveTo(a, b); g.lineTo(a, d); g.stroke() }
    for (let y = Math.ceil(y0); y <= y1; y++) { const [a, b] = P(x0, y); const [c2] = P(x1, y); g.beginPath(); g.moveTo(a, b); g.lineTo(c2, b); g.stroke() }
    const dyn = new Map((frame?.dynamic ?? []).map((d) => [d.id, d]))
    const drawObj = (o: WorldObject) => {
      if (o.kind === 'floor') return
      const d = dyn.get(o.id)
      const cx = d ? d.x : o.pose.xyz[0], cy = d ? d.y : o.pose.xyz[1]
      g.save()
      const [px, py] = P(cx, cy)
      g.translate(px, py); g.rotate(-o.pose.rpy[2])
      g.fillStyle = o.color + (o.kind === 'loading_zone' ? '66' : 'dd')
      if (o.shape === 'marker') { g.beginPath(); g.arc(0, 0, 5, 0, Math.PI * 2); g.fill() }
      else if (o.shape === 'cylinder') { g.beginPath(); g.arc(0, 0, o.size[0] * s, 0, Math.PI * 2); g.fill() }
      else g.fillRect((-o.size[0] / 2) * s, (-o.size[1] / 2) * s, o.size[0] * s, o.size[1] * s)
      g.restore()
    }
    project.world.objects.forEach(drawObj)
    // waypoints
    const sc = project.simulation.scenario
    const wps = sc.mode === 'goal' ? (sc.goal ? [sc.goal] : []) : sc.waypoints
    wps.forEach((w, i) => {
      const [px, py] = P(w[0], w[1])
      g.strokeStyle = '#a78bfa'; g.lineWidth = 2; g.beginPath(); g.arc(px, py, 7, 0, Math.PI * 2); g.stroke()
      g.fillStyle = css.getPropertyValue('--text-secondary'); g.font = '11px sans-serif'; g.fillText(sc.mode === 'goal' ? 'G' : `${i + 1}`, px + 9, py - 6)
    })
    const line = (pts: [number, number][], color: string, w: number, dash: number[] = []) => {
      if (pts.length < 2) return
      g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash); g.beginPath()
      pts.forEach((p, i) => { const [a, b] = P(p[0], p[1]); if (i) g.lineTo(a, b); else g.moveTo(a, b) })
      g.stroke(); g.setLineDash([])
    }
    if (frame?.path) line(frame.path, '#facc15', 2, [6, 4])
    line(trail, '#22c55e', 2)
    line(etrail, '#a78bfa', 1.5, [3, 3])
    if (frame?.scan) {
      g.fillStyle = '#ff4d6d'
      for (const [x, y, hit] of frame.scan) if (hit) { const [a, b] = P(x, y); g.fillRect(a - 1.5, b - 1.5, 3, 3) }
    }
    for (const d of frame?.detections ?? []) { const [a, b] = P(d.x, d.y); g.strokeStyle = '#38bdf8'; g.lineWidth = 1.5; g.strokeRect(a - 6, b - 6, 12, 12) }
    const robot = (x: number, y: number, th: number, color: string, ghost: boolean) => {
      const L = 0.4 * s, Wd = 0.35 * s
      const [px, py] = P(x, y)
      g.save(); g.translate(px, py); g.rotate(-th)
      g.globalAlpha = ghost ? 0.5 : 1
      g.strokeStyle = color; g.lineWidth = 2; g.strokeRect(-L / 2, -Wd / 2, L, Wd)
      g.beginPath(); g.moveTo(0, 0); g.lineTo(L * 0.8, 0); g.stroke()
      g.restore()
    }
    if (frame) {
      robot(Number(frame.row.est_x), Number(frame.row.est_y), Number(frame.row.est_theta), '#a78bfa', true)
      robot(Number(frame.row.x), Number(frame.row.y), Number(frame.row.theta), '#22c55e', false)
      // TF: map -> base_link axes at the true pose
      const [px, py] = P(Number(frame.row.x), Number(frame.row.y)); const th = Number(frame.row.theta)
      g.lineWidth = 1.5
      g.strokeStyle = '#ef4444'; g.beginPath(); g.moveTo(px, py); g.lineTo(px + 18 * Math.cos(th), py - 18 * Math.sin(th)); g.stroke()
      g.strokeStyle = '#22c55e'; g.beginPath(); g.moveTo(px, py); g.lineTo(px - 18 * Math.sin(th), py - 18 * Math.cos(th)); g.stroke()
    }
    // scale bar
    g.fillStyle = css.getPropertyValue('--text-muted'); g.fillRect(16, H - 18, s, 2); g.font = '10px sans-serif'; g.fillText('1 m', 16, H - 22)
  }, [project, frame, trail, etrail, tick, x0, y0, x1, y1])
  return (
    <canvas ref={ref} style={{ width: '100%', height: '100%', display: 'block', cursor: addWp ? 'crosshair' : 'default' }}
      onClick={(e) => {
        if (!addWp) return
        const r = (e.target as HTMLCanvasElement).getBoundingClientRect()
        const { s, ox, oy } = geom.current
        onAdd(+(((e.clientX - r.left) - ox) / s).toFixed(2), +((oy - (e.clientY - r.top)) / s).toFixed(2))
      }} />
  )
}

function Live3D({ project, frame }: { project: Project; frame: Frame | null }) {
  const dyn = new Map((frame?.dynamic ?? []).map((d) => [d.id, d]))
  const scanGeo = useMemo(() => {
    const g = new THREE.BufferGeometry()
    if (frame?.scan) g.setAttribute('position', new THREE.Float32BufferAttribute(frame.scan.filter((p) => p[2]).flatMap((p) => [p[0], p[1], 0.2]), 3))
    return g
  }, [frame])
  const r = frame?.row
  return (
    <Canvas shadows camera={{ position: [8, 14, 14], fov: 45 }}>
      <ambientLight intensity={0.6} /><directionalLight position={[10, 18, 8]} intensity={1.1} castShadow />
      <Grid args={[60, 60]} cellSize={1} infiniteGrid fadeDistance={60} cellColor="#3a4656" sectionColor="#52627a" />
      <group rotation={ZUP}>
        {project.world.objects.map((o) => {
          const d = dyn.get(o.id)
          return <WorldObjectMesh key={o.id} o={d ? { ...o, pose: { ...o.pose, xyz: [d.x, d.y, o.pose.xyz[2]] } } : o} />
        })}
        {r && (
          <group position={[Number(r.x), Number(r.y), 0]} rotation={[0, 0, Number(r.theta)]}>
            <group position={[0, 0, project.robot.drivetrain.wheel_radius]}><RobotModel robot={project.robot} /></group>
          </group>)}
        <points geometry={scanGeo}><pointsMaterial color="#ff4d6d" size={0.06} /></points>
      </group>
      <OrbitControls makeDefault />
    </Canvas>
  )
}
