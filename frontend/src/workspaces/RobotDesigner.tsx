import { GizmoHelper, GizmoViewport, Grid, OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { Download, Hammer, Upload } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api, download } from '../api'
import { RobotModel, ZUP } from '../components/scene'
import { Field, IssueList, Num, Panel, SupportBadge } from '../components/ui'
import { useStore } from '../store'
import type { Drivetrain, Robot } from '../types'

const DRIVES = ['differential', 'four_wheel', 'ackermann', 'mecanum', 'tracked', 'arm', 'mobile_manipulator', 'custom']
const MATERIALS = ['aluminium', 'steel', 'abs', 'pla', 'nylon', 'rubber', 'polyurethane', 'carbon_fiber', 'plywood', 'acrylic']

export default function RobotDesigner() {
  const { project, edit, replace, issues, library, toast, selection, select } = useStore()
  const robot = project!.robot
  const d = robot.drivetrain
  const [tab, setTab] = useState<'links' | 'joints' | 'sensors' | 'actuators'>('links')
  const [frames, setFrames] = useState(true)
  const base = robot.links.find((l) => l.name === robot.base_link)
  const [gen, setGen] = useState({
    chassis: base?.geometry?.size ?? [0.4, 0.3, 0.1], chassis_mass: base?.mass ?? 4, wheel_mass: 0.15,
    motor_ref: robot.actuators[0]?.component_ref ?? 'motor.pololu_37d_50to1_12v', lidar: robot.sensors.some((s) => s.type === 'lidar'),
    imu: robot.sensors.some((s) => s.type === 'imu'), arm_dof: 4,
  })
  const motors = Object.values(library).filter((c) => c.category === 'motors_actuators')
  const controllers = project!.circuit.instances.filter((i) => ['dev_boards', 'sbc', 'microcontrollers'].includes(library[i.component_id]?.category))
  const robotIssues = issues.filter((i) => i.domain === 'robot')
  const motor = library[robot.actuators[0]?.component_ref ?? '']
  const vmax = useMemo(() => {
    const rpm = motor?.ratings.noload_rpm?.value
    return rpm ? (rpm / d.gear_ratio) * 2 * Math.PI / 60 * d.wheel_radius : null
  }, [motor, d.gear_ratio, d.wheel_radius])
  const mass = robot.links.reduce((a, l) => a + l.mass, 0)

  const setD = (k: keyof Drivetrain, v: number | string) => edit((p) => { (p.robot.drivetrain as unknown as Record<string, unknown>)[k] = v }, { merge: true })

  const generate = async () => {
    if (robot.links.length && !confirm('Regenerate links, joints, actuators and sensors from these parameters? Twin ids follow a naming convention so existing schematic bindings are kept.')) return
    const r = await api.post<Robot>('/api/robot/generate', { name: robot.name, drivetrain: d, ...gen })
    replace({ ...project!, robot: { ...r, controller_ref: robot.controller_ref, power: robot.power } })
    toast('ok', `Generated ${r.links.length} links / ${r.joints.length} joints`)
  }

  const importUrdf = async (f: File) => {
    const fd = new FormData(); fd.append('file', f)
    try {
      const r = await api.post<{ robot: Robot; report: { preserved: { element: string; reason: string }[]; warnings: string[] } }>('/api/import/urdf', fd)
      replace({ ...project!, robot: { ...r.robot, drivetrain: d, controller_ref: robot.controller_ref, power: robot.power, actuators: [], sensors: [] },
        preserved: { ...project!.preserved, urdf: r.report.preserved } })
      toast('info', `Imported ${r.robot.links.length} links. ${r.report.preserved.length} unsupported element(s) preserved verbatim; ${r.report.warnings.length} warning(s).`)
    } catch (e) { toast('error', (e as Error).message) }
  }

  return (
    <div className="split" style={{ gridTemplateColumns: '320px 1fr 360px' }}>
      <aside className="scroll" style={{ borderRight: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <div className="col">
          <Panel title="Architecture & drivetrain">
            <div className="fields">
              <Field label="Robot name"><input value={robot.name} onChange={(e) => edit((p) => { p.robot.name = e.target.value.replace(/\s/g, '_') }, { merge: true })} /></Field>
              <Field label="Drive type"><select value={d.drive_type} onChange={(e) => setD('drive_type', e.target.value)}>{DRIVES.map((x) => <option key={x}>{x}</option>)}</select></Field>
              <Field label="Wheel radius"><Num value={d.wheel_radius} step={0.005} unit="m" onChange={(v) => setD('wheel_radius', v)} /></Field>
              <Field label="Wheel width"><Num value={d.wheel_width} step={0.002} unit="m" onChange={(v) => setD('wheel_width', v)} /></Field>
              <Field label="Wheel spacing"><Num value={d.wheel_separation} step={0.01} unit="m" onChange={(v) => setD('wheel_separation', v)} /></Field>
              <Field label="Wheel friction μ"><Num value={d.wheel_friction} step={0.05} onChange={(v) => setD('wheel_friction', v)} /></Field>
              <Field label="Extra gear ratio"><Num value={d.gear_ratio} step={0.1} onChange={(v) => setD('gear_ratio', v)} /></Field>
              <Field label="Max speed"><Num value={d.max_speed} step={0.05} unit="m/s" onChange={(v) => setD('max_speed', v)} /></Field>
              <Field label="Max accel"><Num value={d.max_accel} step={0.1} unit="m/s²" onChange={(v) => setD('max_accel', v)} /></Field>
              <Field label="Max decel"><Num value={d.max_decel} step={0.1} unit="m/s²" onChange={(v) => setD('max_decel', v)} /></Field>
              {d.drive_type === 'ackermann' && <Field label="Steering limit"><Num value={d.max_steering_angle} step={0.05} unit="rad" onChange={(v) => setD('max_steering_angle', v)} /></Field>}
              <Field label="Payload"><Num value={d.payload_kg} step={0.5} unit="kg" onChange={(v) => setD('payload_kg', v)} /></Field>
              <Field label="Rolling resist."><Num value={d.rolling_resistance} step={0.005} onChange={(v) => setD('rolling_resistance', v)} /></Field>
            </div>
          </Panel>
          <Panel title="Generator">
            <div className="fields">
              {['L', 'W', 'H'].map((a, i) => (
                <Field key={a} label={`Chassis ${a}`}><Num value={gen.chassis[i]} step={0.01} unit="m" onChange={(v) => setGen({ ...gen, chassis: gen.chassis.map((c, k) => (k === i ? v : c)) })} /></Field>))}
              <Field label="Chassis mass"><Num value={gen.chassis_mass} step={0.1} unit="kg" onChange={(v) => setGen({ ...gen, chassis_mass: v })} /></Field>
              <Field label="Wheel mass"><Num value={gen.wheel_mass} step={0.01} unit="kg" onChange={(v) => setGen({ ...gen, wheel_mass: v })} /></Field>
              <Field label="Drive motor">
                <select value={gen.motor_ref} onChange={(e) => setGen({ ...gen, motor_ref: e.target.value })} style={{ maxWidth: 160 }}>
                  {motors.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>
              <Field label="2D LiDAR"><input type="checkbox" checked={gen.lidar} onChange={(e) => setGen({ ...gen, lidar: e.target.checked })} /></Field>
              <Field label="IMU"><input type="checkbox" checked={gen.imu} onChange={(e) => setGen({ ...gen, imu: e.target.checked })} /></Field>
              {d.drive_type === 'arm' && <Field label="Arm DoF"><Num value={gen.arm_dof} step={1} min={1} max={7} onChange={(v) => setGen({ ...gen, arm_dof: Math.round(v) })} /></Field>}
              <div className="row"><button className="btn primary" onClick={generate}><Hammer size={14} />Generate structure</button>
                <label className="btn"><Upload size={14} />URDF<input type="file" accept=".urdf,.xml" hidden onChange={(e) => e.target.files?.[0] && importUrdf(e.target.files[0])} /></label></div>
            </div>
          </Panel>
          <Panel title="Controller & power">
            <div className="fields">
              <Field label="Controller hardware">
                <select value={robot.controller_ref ?? ''} onChange={(e) => edit((p) => { p.robot.controller_ref = e.target.value || null })}>
                  <option value="">— none —</option>
                  {controllers.map((c) => <option key={c.id} value={c.id}>{c.id} · {library[c.component_id]?.name}</option>)}</select></Field>
              <Field label="Driver efficiency"><Num value={robot.power.driver_efficiency} step={0.01} onChange={(v) => edit((p) => { p.robot.power.driver_efficiency = v }, { merge: true })} /></Field>
              <Field label="Base load override" hint="Leave empty to derive from the circuit power budget"><Num value={robot.power.base_load_w ?? 0} step={0.5} unit="W"
                onChange={(v) => edit((p) => { p.robot.power.base_load_w = v > 0 ? v : null }, { merge: true })} /></Field>
            </div>
            <p className="xs muted">Controller choices come from the schematic. Communication interfaces are validated from the actual wiring in Circuit Studio.</p>
          </Panel>
        </div>
      </aside>

      <div className="viewport">
        <div className="overlay toolbar" style={{ top: 10, left: 10 }}>
          <button className={`btn sm ${frames ? 'active' : ''}`} onClick={() => setFrames(!frames)}>TF frames</button>
        </div>
        <div className="overlay row" style={{ top: 10, right: 10, gap: 6 }}>
          <div className="panel kpi" style={{ padding: '6px 10px' }}><div className="l">Total mass</div><strong>{(mass + d.payload_kg).toFixed(2)} kg</strong></div>
          <div className="panel kpi" style={{ padding: '6px 10px' }} title="No-load wheel speed from the motor datasheet; loaded speed is lower">
            <div className="l">Motor-limited speed</div><strong>{vmax ? `${vmax.toFixed(2)} m/s` : '—'}</strong></div>
        </div>
        <Canvas shadows camera={{ position: [0.9, 0.7, 0.9], fov: 40, near: 0.01 }} onPointerMissed={() => select([])}>
          <ambientLight intensity={0.6} />
          <directionalLight position={[2, 4, 2]} intensity={1.3} castShadow />
          <Grid args={[10, 10]} cellSize={0.05} sectionSize={0.5} infiniteGrid fadeDistance={6} cellColor="#3a4656" sectionColor="#52627a" />
          <group rotation={ZUP}>
            <RobotModel robot={robot} frames={frames} selectedLink={selection[0]} onSelectLink={(n) => select([n])} />
          </group>
          <OrbitControls makeDefault target={[0, 0.08, 0]} />
          <GizmoHelper alignment="bottom-right" margin={[60, 60]}><GizmoViewport labelColor="white" /></GizmoHelper>
        </Canvas>
      </div>

      <aside className="scroll" style={{ borderLeft: '1px solid var(--border)', background: 'var(--surface-1)' }}>
        <div className="tabs">{(['links', 'joints', 'sensors', 'actuators'] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t} ({robot[t].length})</button>))}</div>
        <div style={{ padding: 8 }}>
          {tab === 'links' && (
            <table className="t"><thead><tr><th>Link</th><th>Geometry</th><th>Mass</th><th>Material</th></tr></thead>
              <tbody>{robot.links.map((l, i) => (
                <tr key={l.name} className={`click ${selection.includes(l.name) ? 'sel' : ''}`} onClick={() => select([l.name])}>
                  <td className="mono">{l.name}</td>
                  <td className="xs">{l.geometry ? `${l.geometry.type} ${l.geometry.size.map((s) => s.toFixed(3)).join('×')}` : <span className="muted">frame only</span>}</td>
                  <td><Num value={l.mass} step={0.01} width={64} onChange={(v) => edit((p) => { p.robot.links[i].mass = v }, { merge: true })} /></td>
                  <td><select value={l.material} onChange={(e) => edit((p) => { p.robot.links[i].material = e.target.value })}>{MATERIALS.map((m) => <option key={m}>{m}</option>)}</select></td>
                </tr>))}</tbody></table>)}
          {tab === 'joints' && (
            <table className="t"><thead><tr><th>Joint</th><th>Type</th><th>Parent → child</th><th>Axis</th></tr></thead>
              <tbody>{robot.joints.map((j) => (
                <tr key={j.name} className={selection.includes(j.name) ? 'sel' : ''}>
                  <td className="mono xs">{j.name}</td><td><span className="chip">{j.type}</span></td>
                  <td className="xs">{j.parent} → {j.child}<div className="muted">xyz {j.origin.xyz.map((v) => v.toFixed(3)).join(', ')}</div></td>
                  <td className="mono xs">{j.type === 'fixed' ? '—' : `[${j.axis.join(', ')}]`}
                    {j.limits && j.type === 'revolute' && <div className="muted">{j.limits.lower.toFixed(2)}…{j.limits.upper.toFixed(2)} rad</div>}</td>
                </tr>))}</tbody></table>)}
          {tab === 'sensors' && (
            <table className="t"><thead><tr><th>Sensor</th><th>Link</th><th>Rate</th><th>Noise σ</th></tr></thead>
              <tbody>{robot.sensors.map((s, i) => (
                <tr key={s.id}><td><strong>{s.id}</strong><div className="muted xs">{s.type}{s.component_ref && ` · ${library[s.component_ref]?.name ?? s.component_ref}`}</div>
                  {s.component_ref && library[s.component_ref] && <SupportBadge status={library[s.component_ref].support_status} />}</td>
                  <td className="mono xs">{s.link}</td>
                  <td><Num value={s.rate_hz} step={1} width={56} unit="Hz" onChange={(v) => edit((p) => { p.robot.sensors[i].rate_hz = v }, { merge: true })} /></td>
                  <td><Num value={s.noise_std} step={0.001} width={60} onChange={(v) => edit((p) => { p.robot.sensors[i].noise_std = v }, { merge: true })} /></td>
                </tr>))}</tbody></table>)}
          {tab === 'actuators' && (
            <table className="t"><thead><tr><th>Actuator</th><th>Joint</th><th>Motor</th><th>Twin id</th></tr></thead>
              <tbody>{robot.actuators.map((a, i) => (
                <tr key={a.id}><td>{a.id}<div className="muted xs">{a.role}</div></td><td className="mono xs">{a.joint}</td>
                  <td><select value={a.component_ref} style={{ maxWidth: 130 }} onChange={(e) => edit((p) => { p.robot.actuators[i].component_ref = e.target.value })}>
                    {motors.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></td>
                  <td className="mono xs">{a.twin_id}</td></tr>))}</tbody></table>)}
        </div>
        <div style={{ padding: 8 }}>
          <Panel title="Robot validation">
            <IssueList issues={robotIssues} compact empty="No robot-model issues." />
          </Panel>
          <Panel title="Robot description export" style={{ marginTop: 8 }}>
            <div className="row wrap">
              {[['urdf', 'URDF'], ['xacro', 'Xacro'], ['sdf', 'SDF'], ['mjcf', 'MJCF']].map(([f, l]) => (
                <button key={f} className="btn sm" onClick={() => download(f, project!).catch((e) => toast('error', e.message))}><Download size={13} />{l}</button>))}
            </div>
          </Panel>
        </div>
      </aside>
    </div>
  )
}
