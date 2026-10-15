import { Download, Play, Search, Trash2, Zap } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, download } from '../api'
import { fmt, IssueList, IssueSummary, Panel, SupportBadge } from '../components/ui'
import { uid, useStore } from '../store'
import type { Component, ComponentInstance, Issue, Pin } from '../types'

const LEFT_TYPES = new Set(['power_in', 'ground', 'digital_in', 'pwm_in', 'uart_rx', 'analog_in', 'spi_mosi', 'spi_sck', 'spi_cs', 'can_tx', 'motor_in', 'passive'])
const PIN_COLORS: Record<string, string> = {
  power_in: '#e5484d', power_out: '#e5484d', ground: '#8b95a5', motor_out: '#d95926', motor_in: '#d95926',
  pwm_in: '#9085e9', digital_io: '#3987e5', digital_in: '#3987e5', digital_out: '#3987e5', encoder_out: '#3987e5',
  i2c_sda: '#199e70', i2c_scl: '#199e70', uart_tx: '#c98500', uart_rx: '#c98500', can_h: '#d55181', can_l: '#d55181',
}
const PREFIX: Record<string, string> = {
  passives: 'R', batteries: 'BT', motors_actuators: 'M', motor_drivers: 'U', dev_boards: 'U', sbc: 'U', sensors: 'U',
  power_electronics: 'U', communication: 'U', analog_ics: 'U', digital_ics: 'U', protection_switching: 'F', connectors: 'J',
}

interface Layout { w: number; h: number; pins: Record<string, { x: number; y: number; side: 'l' | 'r' }> }

function layoutFor(c: Component): Layout {
  const two = c.pins.length === 2 && c.pins.every((p) => ['passive', 'power_out', 'ground'].includes(p.type))
  if (two) return { w: 64, h: 26, pins: { [c.pins[0].id]: { x: 0, y: 13, side: 'l' }, [c.pins[1].id]: { x: 64, y: 13, side: 'r' } } }
  if (c.pins.length === 1) return { w: 40, h: 26, pins: { [c.pins[0].id]: { x: 20, y: 0, side: 'l' } } }
  const left = c.pins.filter((p) => LEFT_TYPES.has(p.type))
  const right = c.pins.filter((p) => !LEFT_TYPES.has(p.type))
  const rows = Math.max(left.length, right.length, 1)
  const h = rows * 14 + 22
  const pins: Layout['pins'] = {}
  left.forEach((p, i) => { pins[p.id] = { x: 0, y: 20 + i * 14, side: 'l' } })
  right.forEach((p, i) => { pins[p.id] = { x: 130, y: 20 + i * 14, side: 'r' } })
  return { w: 130, h, pins }
}

function netsOf(instances: ComponentInstance[], wires: { a: { instance: string; pin: string }; b: { instance: string; pin: string } }[]) {
  const parent = new Map<string, string>()
  const find = (k: string): string => { let r = k; while (parent.get(r) && parent.get(r) !== r) r = parent.get(r)!; parent.set(k, r); return r }
  for (const w of wires) {
    const a = `${w.a.instance}.${w.a.pin}`, b = `${w.b.instance}.${w.b.pin}`
    if (!parent.has(a)) parent.set(a, a)
    if (!parent.has(b)) parent.set(b, b)
    const ra = find(a), rb = find(b)
    if (ra !== rb) parent.set(rb, ra)
  }
  void instances
  return (key: string) => (parent.has(key) ? find(key) : key)
}

interface CheckResult { issues: Issue[]; nets: { id: string; name: string | null; pins: string[]; voltage: number | null }[]; power_budget: Budget }
interface Budget {
  rails: { rail: string; name: string; v_nominal: number | null; source: string | null; capacity_a: number | null; load_typ_a: number; load_peak_a: number; power_typ_w: number; loads: { who: string; typ_a: number; peak_a: number; note: string }[] }[]
  battery: { instance: string; v_nominal: number; current_typ_a: number; current_peak_a: number; power_typ_w: number; runtime_h_estimate: number | null; max_discharge_a: number | null; note: string } | null
  assumptions: string[]
}

export default function CircuitStudio() {
  const { project, edit, library, selection, select, toast } = useStore()
  const circuit = project!.circuit
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [pending, setPending] = useState<{ instance: string; pin: string } | null>(null)
  const [hoverNet, setHoverNet] = useState<string | null>(null)
  const [selWire, setSelWire] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [check, setCheck] = useState<CheckResult | null>(null)
  const [tab, setTab] = useState<'erc' | 'power' | 'nets' | 'sim'>('erc')
  const [mouse, setMouse] = useState<{ x: number; y: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ id?: string; ox: number; oy: number; pan?: boolean; sx: number; sy: number } | null>(null)

  const comps = useMemo(() => Object.fromEntries(circuit.instances.map((i) => [i.id, library[i.component_id]])), [circuit.instances, library])
  const layouts = useMemo(() => Object.fromEntries(circuit.instances.map((i) => [i.id, comps[i.id] ? layoutFor(comps[i.id]) : null])), [circuit.instances, comps])
  const netKey = useMemo(() => netsOf(circuit.instances, circuit.wires), [circuit])
  const issueRefs = useMemo(() => {
    const m: Record<string, string> = {}
    for (const i of check?.issues ?? []) for (const r of i.refs) if (!m[r] || i.severity === 'critical' || i.severity === 'error') m[r] = i.severity
    return m
  }, [check])

  const fit = useCallback(() => {
    const svg = svgRef.current
    if (!svg || !circuit.instances.length) { setView({ x: 0, y: 0, k: 1 }); return }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const i of circuit.instances) {
      const L = layouts[i.id]
      x0 = Math.min(x0, i.position[0]); y0 = Math.min(y0, i.position[1] - 14)
      x1 = Math.max(x1, i.position[0] + (L?.w ?? 100)); y1 = Math.max(y1, i.position[1] + (L?.h ?? 30) + 14)
    }
    const r = svg.getBoundingClientRect()
    const k = Math.min(2, Math.max(0.25, Math.min((r.width - 60) / (x1 - x0), (r.height - 90) / (y1 - y0))))
    setView({ k, x: (r.width - k * (x1 - x0)) / 2 - k * x0, y: 50 + (r.height - 60 - k * (y1 - y0)) / 2 - k * y0 })
  }, [circuit.instances, layouts])
  const fitted = useRef(false)
  useEffect(() => { if (!fitted.current && Object.keys(library).length) { fitted.current = true; fit() } }, [fit, library])

  // live electrical rule check
  useEffect(() => {
    const t = setTimeout(() => {
      api.post<CheckResult>('/api/circuit/check', project).then(setCheck).catch(() => undefined)
    }, 400)
    return () => clearTimeout(t)
  }, [project])

  const toWorld = useCallback((cx: number, cy: number) => {
    const r = svgRef.current!.getBoundingClientRect()
    return { x: (cx - r.left - view.x) / view.k, y: (cy - r.top - view.y) / view.k }
  }, [view])

  const pinPos = (inst: ComponentInstance, pid: string) => {
    const L = layouts[inst.id]
    const p = L?.pins[pid]
    return p ? { x: inst.position[0] + p.x, y: inst.position[1] + p.y } : { x: inst.position[0], y: inst.position[1] }
  }

  const place = (c: Component, x: number, y: number) => {
    const prefix = c.id === 'ground' ? 'G' : c.id.startsWith('passive.capacitor') ? 'C' : c.id.startsWith('passive.inductor') ? 'L'
      : c.id.startsWith('led') || c.id.startsWith('diode') ? 'D' : c.id.startsWith('source') || c.id.startsWith('supply') ? 'V' : PREFIX[c.category] ?? 'X'
    let n = 1
    while (circuit.instances.some((i) => i.id === `${prefix}${n}`)) n++
    const id = `${prefix}${n}`
    edit((p) => { p.circuit.instances.push({ id, component_id: c.id, position: [Math.round(x / 10) * 10, Math.round(y / 10) * 10], rotation: 0, params: {}, twin_id: null }) })
    select([id])
  }

  const clickPin = (inst: string, pin: string) => {
    if (!pending) { setPending({ instance: inst, pin }); return }
    if (pending.instance === inst && pending.pin === pin) { setPending(null); return }
    const dup = circuit.wires.some((w) => (w.a.instance === pending.instance && w.a.pin === pending.pin && w.b.instance === inst && w.b.pin === pin)
      || (w.b.instance === pending.instance && w.b.pin === pending.pin && w.a.instance === inst && w.a.pin === pin))
    if (!dup) edit((p) => { p.circuit.wires.push({ id: uid('W'), a: pending, b: { instance: inst, pin }, label: null }) })
    setPending(null)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT') return
      if (e.key === 'Escape') setPending(null)
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selWire) { edit((p) => { p.circuit.wires = p.circuit.wires.filter((w) => w.id !== selWire) }); setSelWire(null) }
        else if (selection[0] && circuit.instances.some((i) => i.id === selection[0])) {
          const id = selection[0]
          edit((p) => { p.circuit.instances = p.circuit.instances.filter((i) => i.id !== id); p.circuit.wires = p.circuit.wires.filter((w) => w.a.instance !== id && w.b.instance !== id) })
          select([])
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selWire, selection, circuit.instances, edit, select])

  const libItems = useMemo(() => Object.values(library).filter((c) => c.pins.length > 0 && (!q || `${c.name} ${c.id} ${c.tags.join(' ')} ${c.part_number ?? ''}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name)), [library, q])
  const selInst = circuit.instances.find((i) => i.id === selection[0])
  const activeNet = hoverNet

  return (
    <div className="split" style={{ gridTemplateColumns: '250px 1fr 380px' }}>
      <aside className="scroll" style={{ borderRight: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <div className="row" style={{ marginBottom: 8 }}><Search size={14} /><input placeholder="Search parts…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} /></div>
        <div className="xs muted" style={{ marginBottom: 6 }}>Drag a part onto the sheet. Click pin → pin to wire. Del removes, Esc cancels.</div>
        {libItems.map((c, i) => (
          <div key={c.id}>
            {(i === 0 || libItems[i - 1].category !== c.category) && <div className="nav-section" style={{ margin: '10px 0 4px' }}>{c.category.replace(/_/g, ' ')}</div>}
            <div draggable onDragStart={(e) => e.dataTransfer.setData('text/component', c.id)} className="panel" title={c.description || c.name}
              style={{ padding: '5px 8px', marginBottom: 4, cursor: 'grab' }}>
              <div className="small">{c.name}</div>
              <div className="row xs muted" style={{ gap: 4 }}>{c.part_number ?? c.id}<span className="spacer" /><SupportBadge status={c.support_status} compact /></div>
            </div>
          </div>))}
      </aside>

      <div className="viewport" style={{ background: 'var(--surface-2)' }}>
        <div className="overlay toolbar" style={{ top: 10, left: 10 }}>
          <button className="btn sm" onClick={fit}>Fit to view</button>
          {pending && <span className="badge info">Wiring from {pending.instance}.{pending.pin} — click a target pin</span>}
          {check && <IssueSummary issues={check.issues} />}
        </div>
        <svg ref={svgRef} width="100%" height="100%" style={{ display: 'block', cursor: drag.current?.pan ? 'grabbing' : 'default' }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { const id = e.dataTransfer.getData('text/component'); const c = library[id]; if (c) { const p = toWorld(e.clientX, e.clientY); place(c, p.x, p.y) } }}
          onWheel={(e) => {
            const r = svgRef.current!.getBoundingClientRect()
            const k = Math.min(3, Math.max(0.25, view.k * (e.deltaY < 0 ? 1.1 : 0.9)))
            const mx = e.clientX - r.left, my = e.clientY - r.top
            setView({ k, x: mx - ((mx - view.x) * k) / view.k, y: my - ((my - view.y) * k) / view.k })
          }}
          onMouseDown={(e) => { if (e.target === svgRef.current || (e.target as Element).id === 'bg') { drag.current = { pan: true, ox: view.x, oy: view.y, sx: e.clientX, sy: e.clientY }; select([]); setSelWire(null) } }}
          onMouseMove={(e) => {
            const w = toWorld(e.clientX, e.clientY)
            setMouse(w)
            const d = drag.current
            if (!d) return
            if (d.pan) setView({ ...view, x: d.ox + e.clientX - d.sx, y: d.oy + e.clientY - d.sy })
            else if (d.id) {
              const nx = Math.round((d.ox + (e.clientX - d.sx) / view.k) / 10) * 10
              const ny = Math.round((d.oy + (e.clientY - d.sy) / view.k) / 10) * 10
              edit((p) => { const it = p.circuit.instances.find((i) => i.id === d.id); if (it) it.position = [nx, ny] }, { merge: true })
            }
          }}
          onMouseUp={() => { drag.current = null }}>
          <defs>
            <pattern id="dots" width={20} height={20} patternUnits="userSpaceOnUse"><circle cx={1} cy={1} r={1} fill="var(--border-strong)" /></pattern>
          </defs>
          <rect id="bg" width="100%" height="100%" fill="url(#dots)" />
          <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
            {circuit.wires.map((w) => {
              const ia = circuit.instances.find((i) => i.id === w.a.instance), ib = circuit.instances.find((i) => i.id === w.b.instance)
              if (!ia || !ib) return null
              const a = pinPos(ia, w.a.pin), b = pinPos(ib, w.b.pin)
              const net = netKey(`${w.a.instance}.${w.a.pin}`)
              const hi = activeNet === net
              const mx = (a.x + b.x) / 2
              return (
                <g key={w.id} onClick={(e) => { e.stopPropagation(); setSelWire(w.id); select([]) }} style={{ cursor: 'pointer' }}
                  onMouseEnter={() => setHoverNet(net)} onMouseLeave={() => setHoverNet(null)}>
                  <path d={`M${a.x},${a.y} H${mx} V${b.y} H${b.x}`} fill="none" stroke="transparent" strokeWidth={8} />
                  <path d={`M${a.x},${a.y} H${mx} V${b.y} H${b.x}`} fill="none"
                    stroke={selWire === w.id ? '#ffd166' : hi ? 'var(--accent)' : 'var(--text-muted)'} strokeWidth={hi || selWire === w.id ? 2.4 : 1.3} />
                  {w.label && <text x={mx + 3} y={(a.y + b.y) / 2 - 3} fontSize={9} fill="var(--text-secondary)">{w.label}</text>}
                </g>)
            })}
            {pending && mouse && (() => {
              const it = circuit.instances.find((i) => i.id === pending.instance)
              if (!it) return null
              const a = pinPos(it, pending.pin)
              return <line x1={a.x} y1={a.y} x2={mouse.x} y2={mouse.y} stroke="var(--accent)" strokeDasharray="4 3" />
            })()}
            {circuit.instances.map((inst) => {
              const c = comps[inst.id]
              const L = layouts[inst.id]
              if (!c || !L) return (
                <g key={inst.id} transform={`translate(${inst.position[0]},${inst.position[1]})`}>
                  <rect width={110} height={30} fill="none" stroke="var(--critical)" strokeDasharray="4 3" />
                  <text x={4} y={18} fontSize={10} fill="var(--critical)">{inst.id}: unknown part</text>
                </g>)
              const sev = issueRefs[inst.id]
              const sel = selection.includes(inst.id)
              const stroke = sel ? '#ffd166' : sev === 'critical' || sev === 'error' ? 'var(--critical)' : sev === 'warning' ? 'var(--warning)' : 'var(--border-strong)'
              return (
                <g key={inst.id} transform={`translate(${inst.position[0]},${inst.position[1]})`}>
                  <rect width={L.w} height={L.h} rx={4} fill="var(--surface-1)" stroke={stroke} strokeWidth={sel || sev ? 2 : 1}
                    style={{ cursor: 'move' }}
                    onMouseDown={(e) => { e.stopPropagation(); select([inst.id]); setSelWire(null); drag.current = { id: inst.id, ox: inst.position[0], oy: inst.position[1], sx: e.clientX, sy: e.clientY } }} />
                  <text x={L.w / 2} y={L.pins && Object.keys(L.pins).length > 2 ? 12 : -4} textAnchor="middle" fontSize={10} fontWeight={600} fill="var(--text-primary)" pointerEvents="none">
                    {inst.id}
                  </text>
                  {Object.keys(L.pins).length > 2 && <text x={L.w / 2} y={L.h + 11} textAnchor="middle" fontSize={8.5} fill="var(--text-muted)" pointerEvents="none">{c.name.slice(0, 32)}</text>}
                  {Object.keys(L.pins).length <= 2 && <text x={L.w / 2} y={17} textAnchor="middle" fontSize={8.5} fill="var(--text-secondary)" pointerEvents="none">{instValue(inst, c)}</text>}
                  {c.pins.map((p: Pin) => {
                    const pp = L.pins[p.id]
                    if (!pp) return null
                    const key = `${inst.id}.${p.id}`
                    const net = netKey(key)
                    const connected = circuit.wires.some((w) => (w.a.instance === inst.id && w.a.pin === p.id) || (w.b.instance === inst.id && w.b.pin === p.id))
                    const hi = activeNet === net && connected
                    const isPending = pending?.instance === inst.id && pending?.pin === p.id
                    return (
                      <g key={p.id} onMouseEnter={() => setHoverNet(net)} onMouseLeave={() => setHoverNet(null)}
                        onClick={(e) => { e.stopPropagation(); clickPin(inst.id, p.id) }} style={{ cursor: 'crosshair' }}>
                        <circle cx={pp.x} cy={pp.y} r={isPending || hi ? 4.5 : 3.2} fill={connected ? PIN_COLORS[p.type] ?? 'var(--text-secondary)' : 'var(--surface-1)'}
                          stroke={PIN_COLORS[p.type] ?? 'var(--text-secondary)'} strokeWidth={1.4} />
                        {Object.keys(L.pins).length > 2 && (
                          <text x={pp.side === 'l' ? pp.x + 6 : pp.x - 6} y={pp.y + 3} fontSize={8.5} textAnchor={pp.side === 'l' ? 'start' : 'end'}
                            fill={hi ? 'var(--accent)' : 'var(--text-secondary)'} pointerEvents="none">{p.id}</text>)}
                        <title>{`${key} · ${p.type}${p.v_max != null ? ` · ${p.v_min ?? '?'}–${p.v_max} V` : ''}${p.logic_v != null ? ` · ${p.logic_v} V logic` : ''}${p.v_abs_max != null ? ` · abs max ${p.v_abs_max} V` : ''}${p.capabilities.length ? ` · ${p.capabilities.join(', ')}` : ''}`}</title>
                      </g>)
                  })}
                </g>)
            })}
          </g>
        </svg>
      </div>

      <aside className="scroll" style={{ borderLeft: '1px solid var(--border)', background: 'var(--surface-1)' }}>
        {selInst && comps[selInst.id] && <InstanceProps inst={selInst} comp={comps[selInst.id]} />}
        <div className="tabs">
          {(['erc', 'power', 'nets', 'sim'] as const).map((t) => <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {{ erc: 'Rule check', power: 'Power budget', nets: 'Nets', sim: 'Circuit sim' }[t]}</button>)}
        </div>
        <div style={{ padding: 10 }}>
          {tab === 'erc' && (check ? <IssueList issues={check.issues} empty="No electrical or compatibility issues." /> : <div className="muted">Checking…</div>)}
          {tab === 'power' && check && <PowerBudget b={check.power_budget} />}
          {tab === 'nets' && check && (
            <table className="t"><thead><tr><th>Net</th><th className="num">V</th><th>Pins</th></tr></thead>
              <tbody>{check.nets.map((n) => (
                <tr key={n.id} className="click" onMouseEnter={() => setHoverNet(netKey(n.pins[0]))} onMouseLeave={() => setHoverNet(null)}>
                  <td className="mono xs">{n.name ?? n.id}</td><td className="num">{fmt(n.voltage, 2)}</td><td className="xs">{n.pins.join(', ')}</td></tr>))}</tbody></table>)}
          {tab === 'sim' && <CircuitSim />}
          <hr className="sep" />
          <div className="row wrap">
            <button className="btn sm" onClick={() => download('spice', project!).catch((e) => toast('error', e.message))}><Download size={13} />SPICE netlist</button>
            <button className="btn sm" onClick={() => download('kicad', project!).catch((e) => toast('error', e.message))}><Download size={13} />KiCad netlist</button>
          </div>
        </div>
      </aside>
    </div>
  )
}

function instValue(inst: ComponentInstance, c: Component) {
  const p = { ...c.params, ...inst.params } as Record<string, unknown>
  if (p.resistance != null) return `${si(Number(p.resistance))}Ω`
  if (p.capacitance != null) return `${si(Number(p.capacitance))}F`
  if (p.inductance != null) return `${si(Number(p.inductance))}H`
  if (p.voltage != null) return `${p.voltage} V`
  if (p.rating_a != null) return `${p.rating_a} A`
  return c.part_number ?? ''
}
function si(v: number) {
  const units: [number, string][] = [[1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']]
  const u = units.find(([k]) => Math.abs(v) >= k) ?? units[units.length - 1]
  return `${+(v / u[0]).toPrecision(3)}${u[1]}`
}

function InstanceProps({ inst, comp }: { inst: ComponentInstance; comp: Component }) {
  const { edit, project } = useStore()
  const twinIds = [...project!.robot.actuators.map((a) => a.twin_id), ...project!.robot.sensors.filter((s) => s.type !== 'encoder').map((s) => s.twin_id)]
  const editable = Object.entries(comp.params).filter(([, v]) => typeof v === 'number' || typeof v === 'boolean')
  const idx = project!.circuit.instances.findIndex((i) => i.id === inst.id)
  return (
    <div style={{ padding: 10, borderBottom: '1px solid var(--border)' }}>
      <div className="row"><strong>{inst.id}</strong><span className="secondary">{comp.name}</span><span className="spacer" />
        <button className="btn sm icon ghost" title="Delete (Del)" onClick={() => edit((p) => {
          p.circuit.instances.splice(idx, 1); p.circuit.wires = p.circuit.wires.filter((w) => w.a.instance !== inst.id && w.b.instance !== inst.id)
        })}><Trash2 size={13} /></button></div>
      <div className="row wrap xs" style={{ margin: '4px 0' }}>
        <SupportBadge status={comp.support_status} />
        {comp.sim_model && <span className="chip">{comp.sim_model}</span>}
        {comp.datasheet && <a href={comp.datasheet} target="_blank" rel="noreferrer">datasheet</a>}
      </div>
      <div className="fields">
        {editable.map(([k, v]) => (
          <label key={k} className="field"><span>{k}</span>
            {typeof v === 'boolean'
              ? <input type="checkbox" checked={Boolean(inst.params[k] ?? v)} onChange={(e) => edit((p) => { p.circuit.instances[idx].params[k] = e.target.checked })} />
              : <input type="number" step="any" value={Number(inst.params[k] ?? v)} onChange={(e) => { const n = parseFloat(e.target.value); if (Number.isFinite(n)) edit((p) => { p.circuit.instances[idx].params[k] = n }, { merge: true }) }} />}
          </label>))}
        <label className="field"><span>Twin id</span>
          <select value={inst.twin_id ?? ''} onChange={(e) => edit((p) => { p.circuit.instances[idx].twin_id = e.target.value || null })}>
            <option value="">— not bound —</option>{twinIds.map((t) => <option key={t}>{t}</option>)}</select></label>
      </div>
      {comp.compatibility.length > 0 && <div className="xs secondary" style={{ marginTop: 6 }}>{comp.compatibility.map((c) => <div key={c}>• {c}</div>)}</div>}
    </div>
  )
}

function PowerBudget({ b }: { b: Budget }) {
  return (
    <div className="col">
      {b.battery && (
        <Panel title={<span className="row"><Zap size={14} />Battery {b.battery.instance}</span>}>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            <div><div className="muted xs">Typical draw</div><strong>{b.battery.current_typ_a.toFixed(2)} A</strong><div className="xs muted">{b.battery.power_typ_w.toFixed(1)} W</div></div>
            <div><div className="muted xs">Peak (stall)</div><strong>{b.battery.current_peak_a.toFixed(1)} A</strong><div className="xs muted">limit {fmt(b.battery.max_discharge_a, 0)} A</div></div>
            <div><div className="muted xs">Runtime est.</div><strong>{fmt(b.battery.runtime_h_estimate, 1)} h</strong></div>
          </div>
          <div className="xs muted" style={{ marginTop: 6 }}>{b.battery.note}</div>
        </Panel>)}
      {b.rails.map((r) => (
        <div key={r.rail} className="panel" style={{ padding: 8 }}>
          <div className="row"><strong className="small">{r.name}</strong><span className="spacer" />
            <span className="small">{r.load_typ_a.toFixed(3)} A typ / {r.load_peak_a.toFixed(2)} A peak</span>
            {r.capacity_a != null && <span className={`badge ${r.load_typ_a > r.capacity_a ? 'error' : r.load_peak_a > r.capacity_a ? 'warning' : 'good'}`}>cap {r.capacity_a} A</span>}</div>
          {r.capacity_a != null && (
            <div style={{ height: 6, background: 'var(--surface-3)', borderRadius: 3, margin: '6px 0', overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, (r.load_typ_a / r.capacity_a) * 100)}%`, height: '100%', background: 'var(--series-1)', borderRadius: 3 }} />
            </div>)}
          <table className="t"><tbody>{r.loads.map((l, i) => (
            <tr key={i}><td className="mono xs">{l.who}</td><td className="num xs">{l.typ_a.toFixed(3)} A</td><td className="xs muted">{l.note}</td></tr>))}</tbody></table>
        </div>))}
      {b.assumptions.map((a) => <div key={a} className="xs muted">⚠ {a}</div>)}
    </div>
  )
}

function CircuitSim() {
  const { project, toast } = useStore()
  const [res, setRes] = useState<{ status: string; engine: string; nodes?: Record<string, number>; elements?: Record<string, { kind: string; v: number; i: number; p: number }>; skipped: { instance: string; reason: string; support_status: string }[]; errors: string[] } | null>(null)
  const [engine, setEngine] = useState('builtin')
  const run = async () => {
    try { setRes(await api.post('/api/circuit/simulate', project, { analysis: 'op', engine })) } catch (e) { toast('error', (e as Error).message) }
  }
  return (
    <div className="col">
      <div className="row">
        <select value={engine} onChange={(e) => setEngine(e.target.value)}>
          <option value="builtin">Built-in MNA solver</option><option value="ngspice">ngspice (if installed)</option></select>
        <button className="btn primary sm" onClick={run}><Play size={13} />DC operating point</button>
      </div>
      <div className="xs muted">Solves R, C, L, sources, diodes, switches, fuses and battery packs from first principles. Parts without a circuit model are listed below — they are not approximated.</div>
      {res && (
        <>
          <div className="row"><span className={`badge ${res.status === 'ok' ? 'good' : 'error'}`}>{res.status}</span><span className="chip">{res.engine}</span><span className="badge info">circuit-solver result</span></div>
          {res.errors?.map((e) => <div key={e} className="small" style={{ color: 'var(--critical)' }}>{e}</div>)}
          {res.nodes && (
            <table className="t"><thead><tr><th>Node</th><th className="num">Voltage</th></tr></thead>
              <tbody>{Object.entries(res.nodes).map(([k, v]) => <tr key={k}><td className="mono xs">{k}</td><td className="num">{v.toFixed(4)} V</td></tr>)}</tbody></table>)}
          {res.elements && (
            <table className="t"><thead><tr><th>Element</th><th className="num">I</th><th className="num">P</th></tr></thead>
              <tbody>{Object.entries(res.elements).map(([k, v]) => <tr key={k}><td className="mono xs">{k}</td><td className="num">{si(v.i)}A</td><td className="num">{si(v.p)}W</td></tr>)}</tbody></table>)}
          {res.skipped.length > 0 && (
            <div className="xs secondary"><strong>Not simulated ({res.skipped.length}):</strong> {res.skipped.map((s) => `${s.instance} (${s.support_status.replace(/_/g, ' ')})`).join(', ')}</div>)}
        </>)}
    </div>
  )
}
