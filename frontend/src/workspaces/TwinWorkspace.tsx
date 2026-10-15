import { ArrowRight, CheckCircle2, Link2, Wand2, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { IssueList, Panel } from '../components/ui'
import { useStore } from '../store'
import type { Issue, Project } from '../types'

interface Binding {
  actuator: string; joint: string; role: string; twin_id: string; motor: string | null; motor_component: string | null
  driver: string | null; driver_component: string | null; channel: string | null; controller_pin: string | null
  firmware_channel: string | null; encoder_pin: string | null; battery: string | null; bus_voltage: number | null
  fuse: string | null; drivable: boolean; issues: string[]
}

function Hop({ label, value, ok = true, sub }: { label: string; value: string | null; ok?: boolean; sub?: string }) {
  return (
    <div className="panel" style={{ padding: '6px 9px', minWidth: 110, borderColor: value ? (ok ? 'var(--border)' : 'var(--warning)') : 'var(--critical)' }}>
      <div className="xs muted">{label}</div>
      <div className="small mono">{value ?? 'missing'}</div>
      {sub && <div className="xs muted">{sub}</div>}
    </div>
  )
}

export default function TwinWorkspace() {
  const { project, replace, library, toast, select, setWorkspace } = useStore()
  const [data, setData] = useState<{ bindings: Binding[]; issues: Issue[] } | null>(null)
  useEffect(() => { api.post<{ bindings: Binding[]; issues: Issue[] }>('/api/twin', project).then(setData).catch(() => undefined) }, [project])

  const autobind = async () => {
    const r = await api.post<{ project: Project; added_channels: string[] }>('/api/twin/autobind', project)
    replace(r.project)
    toast('ok', r.added_channels.length ? `Added firmware channels: ${r.added_channels.join(', ')}` : 'Bindings already complete; no wiring was changed.')
  }

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 12 }}>
        <div><h1>Unified digital twin</h1>
          <div className="muted">Each mechanical actuator is traced through the real schematic wiring. Nothing is inferred from 3D placement — an unwired motor is not driven in simulation.</div></div>
        <span className="spacer" />
        <button className="btn" onClick={autobind} title="Creates firmware pin-map entries and twin bindings from existing wires; never adds wires"><Wand2 size={14} />Auto-bind from wiring</button>
      </div>
      <div className="grid" style={{ gridTemplateColumns: '1fr 380px', alignItems: 'start' }}>
        <div className="col">
          <Panel title="Actuation chain (mechanical → electrical → firmware → simulation)">
            {!data ? <div className="muted">Resolving…</div> : data.bindings.length === 0 ? <div className="empty">No actuators. Generate a robot in the Robot designer.</div> : (
              <div className="col">
                {data.bindings.map((b) => (
                  <div key={b.actuator} className="col" style={{ gap: 6, paddingBottom: 10, borderBottom: '1px solid var(--border)' }}>
                    <div className="row">
                      {b.drivable ? <CheckCircle2 size={16} color="var(--good)" /> : <XCircle size={16} color="var(--critical)" />}
                      <strong>{b.role.replace('_', ' ')}</strong><span className="mono xs muted">{b.twin_id}</span>
                      <span className={`badge ${b.drivable ? 'good' : 'critical'}`}>{b.drivable ? 'drivable in simulation' : 'not drivable'}</span>
                    </div>
                    <div className="row wrap" style={{ gap: 4 }}>
                      <Hop label="Joint (mechanical)" value={b.joint} />
                      <ArrowRight size={14} className="muted" />
                      <Hop label="Motor" value={b.motor} sub={b.motor_component ? library[b.motor_component]?.name : undefined} />
                      <ArrowRight size={14} className="muted" />
                      <Hop label="Driver channel" value={b.driver ? `${b.driver} ch ${b.channel}` : null} sub={b.driver_component ? library[b.driver_component]?.name : undefined} />
                      <ArrowRight size={14} className="muted" />
                      <Hop label="Controller pin" value={b.controller_pin} />
                      <ArrowRight size={14} className="muted" />
                      <Hop label="Firmware channel" value={b.firmware_channel} ok={!!b.firmware_channel} />
                    </div>
                    <div className="row wrap" style={{ gap: 4 }}>
                      <Hop label="Power source" value={b.battery} sub={b.bus_voltage ? `${b.bus_voltage} V nominal` : undefined} />
                      <Hop label="Fuse" value={b.fuse} ok={!!b.fuse} />
                      <Hop label="Encoder feedback" value={b.encoder_pin} ok={!!b.encoder_pin} sub={b.encoder_pin ? 'closed loop' : 'open loop'} />
                      <Hop label="Simulation entity" value={b.joint} sub="physics joint torque" />
                    </div>
                  </div>))}
              </div>)}
          </Panel>
          <Panel title="Shared identities" bodyClass="">
            <table className="t"><thead><tr><th>Twin id</th><th>Label</th><th>Mechanical</th><th>Electrical</th><th>Firmware channels</th><th>Sim entity</th></tr></thead>
              <tbody>{project!.bindings.map((b) => (
                <tr key={b.twin_id} className="click" onClick={() => select([b.mechanical ?? '', b.electrical ?? ''].filter(Boolean))}>
                  <td className="mono xs">{b.twin_id}</td><td>{b.label}</td><td className="mono xs">{b.mechanical}</td>
                  <td className="mono xs"><a onClick={(e) => { e.stopPropagation(); select([b.electrical ?? '']); setWorkspace('circuit') }}>{b.electrical}</a></td>
                  <td className="xs">{b.firmware_channels.join(', ')}</td><td className="mono xs">{b.sim_entity}</td>
                </tr>))}</tbody></table>
          </Panel>
        </div>
        <Panel title={<span className="row"><Link2 size={14} />Twin integrity</span>}>
          {data ? <IssueList issues={data.issues} empty="Every actuator is fully bound." /> : null}
        </Panel>
      </div>
    </div>
  )
}
