import { Download, FileCode2, Hammer, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, download } from '../api'
import { Field, IssueList, Num, Panel } from '../components/ui'
import { useStore } from '../store'

interface Target { id: string; name: string; modes: string[]; logic_v: number; notes: string; platformio: Record<string, string>; max_loop_hz: number }
interface Build { status: string; message?: string; diagnostics: { file: string; line: number; column: number | null; severity: string; message: string }[]; log?: string; note?: string; artifacts?: Record<string, string> }

const FUNCS = ['pwm', 'gpio_out', 'gpio_in', 'adc', 'uart_tx', 'uart_rx', 'i2c_sda', 'i2c_scl', 'spi_mosi', 'spi_miso', 'spi_sck', 'can_tx', 'can_rx', 'encoder']
const MODE_INFO: Record<string, string> = {
  behavioral: 'Behavioural controller model inside the co-simulator (same algorithm as the generated firmware).',
  hal_mock: 'Firmware logic against a mocked hardware abstraction layer; no instruction-level emulation.',
  emulated: 'Instruction-level emulation — offered only for targets with a validated emulator.',
  hil: 'Hardware-in-the-loop: the real board runs the generated firmware and talks to the simulator over serial.',
}

export default function FirmwareWorkspace() {
  const { project, edit, library, issues, toast } = useStore()
  const fw = project!.firmware
  const [targets, setTargets] = useState<Target[]>([])
  const [files, setFiles] = useState<Record<string, string>>({})
  const [open, setOpen] = useState('src/main.cpp')
  const [build, setBuild] = useState<Build | null>(null)
  const [building, setBuilding] = useState(false)
  useEffect(() => { api.get<Target[]>('/api/firmware/targets').then(setTargets) }, [])
  useEffect(() => {
    const t = setTimeout(() => api.post<Record<string, string>>('/api/firmware/generate', project).then(setFiles).catch(() => undefined), 400)
    return () => clearTimeout(t)
  }, [project])
  const target = targets.find((t) => t.id === fw.target)
  const ctrl = project!.circuit.instances.find((i) => i.id === project!.robot.controller_ref)
  const ctrlComp = ctrl ? library[ctrl.component_id] : undefined
  const pins = ctrlComp?.pins.filter((p) => p.type === 'digital_io') ?? []
  const fwIssues = issues.filter((i) => i.domain === 'firmware')
  const userFile = fw.files.find((f) => f.path === open)

  const runBuild = async () => {
    setBuilding(true)
    try { setBuild(await api.post<Build>('/api/firmware/build', project)) } catch (e) { toast('error', (e as Error).message) } finally { setBuilding(false) }
  }

  return (
    <div className="split" style={{ gridTemplateColumns: '400px 1fr' }}>
      <aside className="scroll" style={{ borderRight: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <div className="col">
          <Panel title="Target & execution mode">
            <div className="fields">
              <Field label="Target"><select value={fw.target} onChange={(e) => edit((p) => { p.firmware.target = e.target.value })}>
                {targets.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
              <Field label="Mode"><select value={fw.mode} onChange={(e) => edit((p) => { p.firmware.mode = e.target.value })}>
                {['behavioral', 'hal_mock', 'emulated', 'hil'].map((m) => <option key={m} value={m} disabled={!!target && !target.modes.includes(m)}>
                  {m}{target && !target.modes.includes(m) ? ' (not validated for this target)' : ''}</option>)}</select></Field>
            </div>
            <div className="xs secondary" style={{ marginTop: 6 }}>{MODE_INFO[fw.mode]}</div>
            {target?.notes && <div className="xs muted" style={{ marginTop: 4 }}>{target.notes}</div>}
            <div className="xs muted" style={{ marginTop: 4 }}>Controller board: {ctrl ? `${ctrl.id} · ${ctrlComp?.name}` : 'none selected (Robot designer)'}</div>
          </Panel>
          <Panel title="Control loop (diff-drive PI per wheel)">
            <div className="fields">
              <Field label="Loop rate"><Num value={fw.controller.loop_hz} step={10} unit="Hz" onChange={(v) => edit((p) => { p.firmware.controller.loop_hz = v }, { merge: true })} /></Field>
              <Field label="Kp"><Num value={fw.controller.kp} step={0.05} onChange={(v) => edit((p) => { p.firmware.controller.kp = v }, { merge: true })} /></Field>
              <Field label="Ki"><Num value={fw.controller.ki} step={0.1} onChange={(v) => edit((p) => { p.firmware.controller.ki = v }, { merge: true })} /></Field>
              <Field label="Feed-forward"><Num value={fw.controller.feedforward} step={0.05} onChange={(v) => edit((p) => { p.firmware.controller.feedforward = v }, { merge: true })} /></Field>
            </div>
          </Panel>
          <Panel title="Pin map (GPIO / PWM / ADC / UART / I2C / SPI / CAN)" bodyClass="">
            <table className="t"><thead><tr><th>Channel</th><th>Pin</th><th>Function</th><th /></tr></thead>
              <tbody>{fw.pin_map.map((a, i) => {
                const pin = pins.find((p) => p.id === a.pin)
                return (
                  <tr key={i}>
                    <td><input value={a.channel} style={{ width: 120 }} onChange={(e) => edit((p) => { p.firmware.pin_map[i].channel = e.target.value }, { merge: true })} /></td>
                    <td><select value={a.pin} onChange={(e) => edit((p) => { p.firmware.pin_map[i].pin = e.target.value })}>
                      {!pin && <option>{a.pin}</option>}{pins.map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}</select>
                      {pin && <div className="xs muted">{pin.capabilities.join(' ')}</div>}</td>
                    <td><select value={a.function} onChange={(e) => edit((p) => { p.firmware.pin_map[i].function = e.target.value })}>{FUNCS.map((f) => <option key={f}>{f}</option>)}</select></td>
                    <td><button className="btn sm icon ghost" onClick={() => edit((p) => { p.firmware.pin_map.splice(i, 1) })}><Trash2 size={12} /></button></td>
                  </tr>)
              })}</tbody></table>
            <div style={{ padding: 8 }}><button className="btn sm" onClick={() => edit((p) => { p.firmware.pin_map.push({ channel: 'new_channel', pin: pins[0]?.id ?? '', function: 'gpio_out' }) })}><Plus size={13} />Add channel</button></div>
          </Panel>
          <Panel title="Firmware checks"><IssueList issues={fwIssues} compact empty="Pin map and mode are consistent." /></Panel>
        </div>
      </aside>
      <div className="col" style={{ padding: 10, overflow: 'hidden', height: '100%' }}>
        <div className="row">
          <div className="tabs" style={{ flex: 1 }}>{Object.keys(files).concat(fw.files.map((f) => f.path).filter((p) => !(p in files))).map((f) => (
            <button key={f} className={`tab ${open === f ? 'active' : ''}`} onClick={() => setOpen(f)}><FileCode2 size={12} /> {f}</button>))}</div>
          <button className="btn" disabled={building} onClick={runBuild}><Hammer size={14} />{building ? 'Building…' : 'Build (PlatformIO)'}</button>
          <button className="btn" onClick={() => download('firmware', project!).catch((e) => toast('error', e.message))}><Download size={14} />Project .zip</button>
        </div>
        <div className="row xs muted">
          {userFile ? 'User source (overrides generated file)' : 'Generated from the project — edits below create a user override saved in the project.'}
          <span className="spacer" />
          {userFile && <button className="btn sm" onClick={() => edit((p) => { p.firmware.files = p.firmware.files.filter((f) => f.path !== open) })}>Revert to generated</button>}
        </div>
        <textarea style={{ flex: 1, minHeight: 200, resize: 'none' }} spellCheck={false} value={userFile?.content ?? files[open] ?? ''}
          onChange={(e) => edit((p) => {
            const f = p.firmware.files.find((x) => x.path === open)
            if (f) f.content = e.target.value; else p.firmware.files.push({ path: open, content: e.target.value })
          }, { merge: true })} />
        {build && (
          <Panel title={<span className="row">Build result <span className={`badge ${build.status === 'success' ? 'good' : build.status === 'unavailable' || build.status === 'not_applicable' ? '' : 'error'}`}>{build.status}</span></span>} style={{ maxHeight: 260, overflow: 'auto' }}>
            {build.message && <div className="small secondary">{build.message}</div>}
            {build.diagnostics.map((d, i) => (
              <div key={i} className={`issue ${d.severity === 'error' ? 'error' : 'warning'}`} style={{ marginTop: 4 }}>
                <span className="mono xs">{d.file}:{d.line}{d.column ? `:${d.column}` : ''}</span> — {d.message}</div>))}
            {build.note && <div className="xs muted" style={{ marginTop: 6 }}>{build.note}</div>}
            {build.log && <pre className="code" style={{ maxHeight: 140, marginTop: 6 }}>{build.log}</pre>}
          </Panel>)}
      </div>
    </div>
  )
}
