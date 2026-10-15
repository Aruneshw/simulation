import { GizmoHelper, GizmoViewport, Grid, OrbitControls, PointerLockControls, TransformControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Box, Camera, Copy, Eye, Footprints, Move3D, Ruler, RotateCw, Scale3D, Shield, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { api } from '../api'
import { Label, RobotModel, WorldObjectMesh, ZUP } from '../components/scene'
import { Field, Num, Panel } from '../components/ui'
import { uid, useStore } from '../store'
import type { World, WorldObject } from '../types'

const PALETTE: { kind: string; label: string; shape: WorldObject['shape']; size: number[]; color: string }[] = [
  { kind: 'wall', label: 'Wall', shape: 'box', size: [3, 0.15, 2.5], color: '#c9ced6' },
  { kind: 'door', label: 'Door', shape: 'box', size: [0.9, 0.05, 2.0], color: '#b45309' },
  { kind: 'box', label: 'Box obstacle', shape: 'box', size: [0.6, 0.6, 0.6], color: '#f97316' },
  { kind: 'cylinder', label: 'Cylinder / pillar', shape: 'cylinder', size: [0.25, 0.25, 1.2], color: '#e11d48' },
  { kind: 'ramp', label: 'Ramp', shape: 'box', size: [2, 1, 0.3], color: '#a8a29e' },
  { kind: 'stairs', label: 'Stairs', shape: 'box', size: [1, 1.2, 0.6], color: '#94a3b8' },
  { kind: 'platform', label: 'Platform', shape: 'box', size: [2, 2, 0.4], color: '#64748b' },
  { kind: 'rack', label: 'Pallet rack', shape: 'box', size: [2.7, 1.1, 2.0], color: '#d98e04' },
  { kind: 'table', label: 'Table', shape: 'box', size: [1.6, 0.8, 0.9], color: '#94a3b8' },
  { kind: 'workstation', label: 'Workstation', shape: 'box', size: [2, 1.2, 1], color: '#64748b' },
  { kind: 'loading_zone', label: 'Loading zone', shape: 'plane', size: [3, 2, 0.01], color: '#facc15' },
  { kind: 'charging_station', label: 'Charging station', shape: 'box', size: [0.4, 0.3, 0.3], color: '#22c55e' },
  { kind: 'human', label: 'Human (moving)', shape: 'cylinder', size: [0.25, 0.25, 1.75], color: '#3b82f6' },
  { kind: 'robot_start', label: 'Robot start', shape: 'marker', size: [0.3, 0.3, 0.01], color: '#10b981' },
  { kind: 'goal', label: 'Target location', shape: 'marker', size: [0.3, 0.3, 0.01], color: '#ef4444' },
]

type Mode = 'translate' | 'rotate' | 'scale'
type View = 'perspective' | 'top' | 'front' | 'side'

function CameraRig({ view, fps }: { view: View; fps: boolean }) {
  const { camera } = useThree()
  useEffect(() => {
    if (fps) { camera.position.set(0, 1.6, 6); camera.lookAt(0, 1.6, 0); return }
    const p = { perspective: [10, 12, 14], top: [0, 28, 0.001], front: [0, 3, 22], side: [22, 3, 0] }[view]
    camera.position.set(p[0], p[1], p[2])
    camera.lookAt(0, 0, 0)
  }, [view, fps, camera])
  return null
}

function WalkControls() {
  const keys = useRef<Record<string, boolean>>({})
  const { camera } = useThree()
  useEffect(() => {
    const d = (e: KeyboardEvent) => { keys.current[e.code] = true }
    const u = (e: KeyboardEvent) => { keys.current[e.code] = false }
    window.addEventListener('keydown', d); window.addEventListener('keyup', u)
    return () => { window.removeEventListener('keydown', d); window.removeEventListener('keyup', u) }
  }, [])
  useFrame((_, dt) => {
    const k = keys.current
    const v = new THREE.Vector3()
    camera.getWorldDirection(v); v.y = 0; v.normalize()
    const side = new THREE.Vector3().crossVectors(v, camera.up).normalize()
    const s = (k.ShiftLeft ? 6 : 2.5) * dt
    if (k.KeyW) camera.position.addScaledVector(v, s)
    if (k.KeyS) camera.position.addScaledVector(v, -s)
    if (k.KeyD) camera.position.addScaledVector(side, s)
    if (k.KeyA) camera.position.addScaledVector(side, -s)
  })
  return <PointerLockControls />
}

function Selected({ o, mode, snap, onChange }: { o: WorldObject; mode: Mode; snap: boolean; onChange: (pose: { xyz: number[]; yaw: number; scale: number[] }) => void }) {
  const ref = useRef<THREE.Group>(null!)
  const [x, y, z] = o.pose.xyz
  const h = o.shape === 'plane' || o.shape === 'marker' ? 0 : o.size[2] / 2
  return (
    <TransformControls mode={mode} translationSnap={snap ? 0.1 : null} rotationSnap={snap ? Math.PI / 12 : null}
      showZ={mode === 'translate'} showX={mode !== 'rotate'} showY={mode !== 'rotate'}
      onMouseUp={() => {
        const g = ref.current
        const yaw = new THREE.Euler().setFromQuaternion(g.quaternion, 'ZYX').z
        onChange({ xyz: [g.position.x, g.position.y, Math.max(0, g.position.z - h)], yaw, scale: [g.scale.x, g.scale.y, g.scale.z] })
        g.scale.set(1, 1, 1)
      }}>
      <group ref={ref} position={[x, y, z + h]} rotation={[0, 0, o.pose.rpy[2]]}>
        {/* the selected object itself rides inside the gizmo so moves/scales are visible while dragging */}
        <WorldObjectMesh o={{ ...o, pose: { xyz: [0, 0, -h], rpy: [o.pose.rpy[0], o.pose.rpy[1], 0] } }} selected />
      </group>
    </TransformControls>
  )
}

function Measure({ points }: { points: THREE.Vector3[] }) {
  if (points.length === 0) return null
  const [a, b] = points
  return (
    <group>
      {points.map((p, i) => <mesh key={i} position={p}><sphereGeometry args={[0.06, 12, 8]} /><meshBasicMaterial color="#ffd166" /></mesh>)}
      {b && (
        <>
          <line>
            <bufferGeometry onUpdate={(g) => g.setFromPoints([a, b])} />
            <lineBasicMaterial color="#ffd166" />
          </line>
          <Label text={`${a.distanceTo(b).toFixed(3)} m`} position={a.clone().lerp(b, 0.5).add(new THREE.Vector3(0, 0, 0.25)).toArray() as [number, number, number]} color="#ffd166" />
        </>
      )}
    </group>
  )
}

export default function WorldBuilder() {
  const { project, edit, replace, selection, select } = useStore()
  const [mode, setMode] = useState<Mode>('translate')
  const [view, setView] = useState<View>('perspective')
  const [snap, setSnap] = useState(true)
  const [collision, setCollision] = useState(false)
  const [fps, setFps] = useState(false)
  const [measure, setMeasure] = useState(false)
  const [mpts, setMpts] = useState<THREE.Vector3[]>([])
  const [templates, setTemplates] = useState<string[]>([])
  useEffect(() => { api.get<{ worlds: string[] }>('/api/templates').then((t) => setTemplates(t.worlds)) }, [])
  const world = project!.world
  const sel = world.objects.find((o) => o.id === selection[0])
  const start = world.objects.find((o) => o.kind === 'robot_start')
  const waypoints = project!.simulation.scenario.waypoints

  const updateObj = (id: string, fn: (o: WorldObject) => void, merge = false) =>
    edit((p) => { const o = p.world.objects.find((x) => x.id === id); if (o) fn(o) }, { merge })

  const add = (item: (typeof PALETTE)[number]) => {
    const id = uid(item.kind.slice(0, 3) + '_')
    edit((p) => {
      p.world.objects.push({
        id, name: item.label, kind: item.kind, shape: item.shape, size: [...item.size], pose: { xyz: [0, 0, 0], rpy: [0, 0, 0] },
        color: item.color, static: item.kind !== 'human', collision: { enabled: !['loading_zone', 'robot_start', 'goal'].includes(item.kind), friction: 0.8, restitution: 0 },
        motion: item.kind === 'human' ? { type: 'patrol', waypoints: [[-2, 0], [2, 0]], speed: 0.6 } : null, props: {},
      })
    })
    select([id])
  }

  const loadTemplate = async (name: string) => {
    if (!confirm(`Replace the current environment with the "${name}" template?`)) return
    const w = await api.get<World>(`/api/world-templates/${name}`)
    replace({ ...project!, world: w })
  }

  const grouped = useMemo(() => {
    const g: Record<string, WorldObject[]> = {}
    for (const o of world.objects) (g[o.kind] ??= []).push(o)
    return g
  }, [world.objects])

  return (
    <div className="split" style={{ gridTemplateColumns: '230px 1fr 290px' }}>
      <aside className="scroll" style={{ borderRight: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <h4 style={{ marginBottom: 6 }}>Environment template</h4>
        <select style={{ width: '100%' }} value="" onChange={(e) => e.target.value && loadTemplate(e.target.value)}>
          <option value="">{world.template ? `Current: ${world.template}` : 'Choose template…'}</option>
          {templates.map((t) => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
        </select>
        <h4 style={{ margin: '12px 0 6px' }}>Add object</h4>
        <div className="col" style={{ gap: 3 }}>
          {PALETTE.map((p) => (
            <button key={p.kind} className="nav-item" onClick={() => add(p)}>
              <span className="status-dot" style={{ background: p.color }} />{p.label}
            </button>))}
        </div>
        <h4 style={{ margin: '12px 0 6px' }}>Scene hierarchy ({world.objects.length})</h4>
        {Object.entries(grouped).map(([k, objs]) => (
          <div key={k}>
            <div className="xs muted" style={{ marginTop: 6 }}>{k.replace(/_/g, ' ')}</div>
            {objs.map((o) => (
              <button key={o.id} className={`nav-item ${selection.includes(o.id) ? 'active' : ''}`} style={{ padding: '3px 10px' }}
                onClick={() => select([o.id])}>{o.name}{o.motion && <span className="chip">dynamic</span>}</button>))}
          </div>))}
      </aside>

      <div className="viewport">
        <div className="overlay toolbar" style={{ top: 10, left: 10 }}>
          <button className={`btn icon ${mode === 'translate' ? 'active' : ''}`} title="Move (snap 0.1 m)" onClick={() => setMode('translate')}><Move3D size={15} /></button>
          <button className={`btn icon ${mode === 'rotate' ? 'active' : ''}`} title="Rotate (yaw)" onClick={() => setMode('rotate')}><RotateCw size={15} /></button>
          <button className={`btn icon ${mode === 'scale' ? 'active' : ''}`} title="Scale" onClick={() => setMode('scale')}><Scale3D size={15} /></button>
          <button className={`btn sm ${snap ? 'active' : ''}`} onClick={() => setSnap(!snap)}>Snap</button>
          <button className={`btn icon ${collision ? 'active' : ''}`} title="Show collision geometry" onClick={() => setCollision(!collision)}><Shield size={15} /></button>
          <button className={`btn icon ${measure ? 'active' : ''}`} title="Measure: click two points on the floor" onClick={() => { setMeasure(!measure); setMpts([]) }}><Ruler size={15} /></button>
        </div>
        <div className="overlay toolbar" style={{ top: 10, right: 10 }}>
          {(['perspective', 'top', 'front', 'side'] as View[]).map((v) => (
            <button key={v} className={`btn sm ${view === v && !fps ? 'active' : ''}`} onClick={() => { setFps(false); setView(v) }}>
              {v === 'perspective' ? <Camera size={13} /> : <Eye size={13} />}{v}</button>))}
          <button className={`btn sm ${fps ? 'active' : ''}`} title="First-person: click the view, WASD to walk, Esc to exit" onClick={() => setFps(!fps)}><Footprints size={13} />walk</button>
        </div>
        {fps && <div className="overlay panel xs" style={{ bottom: 10, left: 10, padding: 6 }}>Click to look around · WASD move · Shift run · Esc release</div>}
        <Canvas shadows camera={{ fov: 45, near: 0.05, far: 500 }} onPointerMissed={() => !measure && select([])}>
          <CameraRig view={view} fps={fps} />
          <ambientLight intensity={0.55} />
          <directionalLight position={[10, 18, 8]} intensity={1.2} castShadow shadow-mapSize={[2048, 2048]}
            shadow-camera-left={-20} shadow-camera-right={20} shadow-camera-top={20} shadow-camera-bottom={-20} />
          <Grid args={[60, 60]} cellSize={0.5} sectionSize={5} infiniteGrid fadeDistance={60} cellColor="#3a4656" sectionColor="#52627a" />
          <group rotation={ZUP}>
            <mesh visible={false} onPointerDown={(e) => {
              if (!measure) return
              e.stopPropagation()
              const p = e.point.clone().applyEuler(new THREE.Euler(Math.PI / 2, 0, 0))
              p.z = 0.02
              setMpts((pts) => (pts.length >= 2 ? [p] : [...pts, p]))
            }}>
              <planeGeometry args={[200, 200]} />
            </mesh>
            {world.objects.filter((o) => !(sel && o.id === sel.id && !fps && !measure)).map((o) => (
              <WorldObjectMesh key={o.id} o={o} selected={selection.includes(o.id)} showCollision={collision}
                onSelect={(e) => { if (measure) return; e.stopPropagation(); select([o.id]) }} />))}
            {sel && !fps && !measure && (
              <Selected key={sel.id + mode} o={sel} mode={mode} snap={snap} onChange={({ xyz, yaw, scale }) => updateObj(sel.id, (o) => {
                o.pose.xyz = xyz.map((v) => +v.toFixed(3))
                o.pose.rpy = [o.pose.rpy[0], o.pose.rpy[1], +yaw.toFixed(4)]
                if (mode === 'scale') o.size = o.size.map((s, i) => +(s * (o.shape === 'cylinder' && i === 1 ? scale[0] : scale[i])).toFixed(3))
              })} />)}
            {start && (
              <group position={[start.pose.xyz[0], start.pose.xyz[1], 0]} rotation={[0, 0, start.pose.rpy[2]]}>
                <group position={[0, 0, project!.robot.drivetrain.wheel_radius]}><RobotModel robot={project!.robot} /></group>
              </group>)}
            {waypoints.map((w, i) => (
              <group key={i} position={[w[0], w[1], 0.02]}>
                <mesh rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[0.12, 0.12, 0.02, 20]} /><meshBasicMaterial color="#a78bfa" /></mesh>
                <Label text={`WP${i + 1}`} position={[0, 0, 0.45]} />
              </group>))}
            {world.objects.filter((o) => o.motion).map((o) => (
              <line key={o.id + '_path'}>
                <bufferGeometry onUpdate={(g) => g.setFromPoints(o.motion!.waypoints.map((w) => new THREE.Vector3(w[0], w[1], 0.03)))} />
                <lineDashedMaterial color="#3b82f6" dashSize={0.2} gapSize={0.1} />
              </line>))}
            <Measure points={mpts} />
          </group>
          {fps ? <WalkControls /> : <OrbitControls makeDefault enableDamping maxPolarAngle={view === 'perspective' ? Math.PI / 2.05 : Math.PI} />}
          <GizmoHelper alignment="bottom-right" margin={[60, 60]}><GizmoViewport labelColor="white" axisHeadScale={0.9} /></GizmoHelper>
        </Canvas>
      </div>

      <aside className="scroll" style={{ borderLeft: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        {sel ? <Properties o={sel} update={(fn, merge) => updateObj(sel.id, fn, merge)} onDelete={() => { edit((p) => { p.world.objects = p.world.objects.filter((x) => x.id !== sel.id) }); select([]) }}
          onDuplicate={() => { const id = uid('dup_'); edit((p) => { const c = structuredClone(sel); c.id = id; c.name += ' copy'; c.pose.xyz = [c.pose.xyz[0] + 0.5, c.pose.xyz[1] + 0.5, c.pose.xyz[2]]; p.world.objects.push(c) }); select([id]) }} />
          : <WorldProps world={world} />}
      </aside>
    </div>
  )
}

function WorldProps({ world }: { world: World }) {
  const { edit } = useStore()
  return (
    <Panel title="World settings">
      <div className="fields">
        <Field label="Bounds x min"><Num value={world.bounds[0]} step={0.5} onChange={(v) => edit((p) => { p.world.bounds[0] = v })} unit="m" /></Field>
        <Field label="Bounds y min"><Num value={world.bounds[1]} step={0.5} onChange={(v) => edit((p) => { p.world.bounds[1] = v })} unit="m" /></Field>
        <Field label="Bounds x max"><Num value={world.bounds[2]} step={0.5} onChange={(v) => edit((p) => { p.world.bounds[2] = v })} unit="m" /></Field>
        <Field label="Bounds y max"><Num value={world.bounds[3]} step={0.5} onChange={(v) => edit((p) => { p.world.bounds[3] = v })} unit="m" /></Field>
        <Field label="Gravity z"><Num value={world.gravity[2]} onChange={(v) => edit((p) => { p.world.gravity[2] = v })} unit="m/s²" /></Field>
      </div>
      <p className="xs muted">Select an object to edit its geometry, pose, material and collision settings. Collision geometry is used by the physics engines, LiDAR ray casting and the planner — not just for rendering.</p>
    </Panel>
  )
}

function Properties({ o, update, onDelete, onDuplicate }: {
  o: WorldObject; update: (fn: (o: WorldObject) => void, merge?: boolean) => void; onDelete: () => void; onDuplicate: () => void
}) {
  const deg = (r: number) => (r * 180) / Math.PI
  return (
    <div className="col">
      <Panel title={<span className="row"><Box size={14} />{o.name}</span>} actions={<>
        <button className="btn sm icon" title="Duplicate" onClick={onDuplicate}><Copy size={13} /></button>
        <button className="btn sm icon" title="Delete" onClick={onDelete}><Trash2 size={13} /></button></>}>
        <div className="fields">
          <Field label="Name"><input value={o.name} onChange={(e) => update((x) => { x.name = e.target.value }, true)} /></Field>
          <Field label="Kind"><span className="chip">{o.kind}</span></Field>
          <Field label="Id"><span className="mono xs">{o.id}</span></Field>
          <h4>Pose</h4>
          {['x', 'y', 'z'].map((a, i) => (
            <Field key={a} label={a}><Num value={o.pose.xyz[i]} step={0.05} unit="m" onChange={(v) => update((x) => { x.pose.xyz[i] = v }, true)} /></Field>))}
          <Field label="Yaw"><Num value={deg(o.pose.rpy[2])} step={5} unit="°" onChange={(v) => update((x) => { x.pose.rpy[2] = (v * Math.PI) / 180 }, true)} /></Field>
          {o.shape !== 'marker' && <>
            <h4>Geometry ({o.shape})</h4>
            {(o.shape === 'cylinder' ? [['radius', 0], ['height', 2]] : [['size x', 0], ['size y', 1], ['size z', 2]]).map(([l, i]) => (
              <Field key={l} label={String(l)}><Num value={o.size[i as number]} step={0.05} min={0.001} unit="m"
                onChange={(v) => update((x) => { x.size[i as number] = v; if (x.shape === 'cylinder' && i === 0) x.size[1] = v }, true)} /></Field>))}
          </>}
          <h4>Material</h4>
          <Field label="Color"><input type="color" value={o.color} onChange={(e) => update((x) => { x.color = e.target.value }, true)} /></Field>
          <h4>Physics</h4>
          <Field label="Collision"><input type="checkbox" checked={o.collision.enabled} onChange={(e) => update((x) => { x.collision.enabled = e.target.checked })} /></Field>
          <Field label="Friction μ"><Num value={o.collision.friction} step={0.05} min={0} onChange={(v) => update((x) => { x.collision.friction = v }, true)} /></Field>
          <Field label="Static"><input type="checkbox" checked={o.static} onChange={(e) => update((x) => { x.static = e.target.checked })} /></Field>
        </div>
      </Panel>
      {o.kind === 'charging_station' && (
        <Panel title="Docking">
          <Field label="Charge power"><Num value={Number(o.props.charge_power_w ?? 120)} step={10} unit="W" onChange={(v) => update((x) => { x.props.charge_power_w = v }, true)} /></Field>
          <p className="xs muted">The dock pose (where the robot stops) defaults to 0.6 m in front of the station.</p>
        </Panel>)}
      {o.motion && (
        <Panel title="Dynamic obstacle path">
          <Field label="Speed"><Num value={o.motion.speed} step={0.1} unit="m/s" onChange={(v) => update((x) => { x.motion!.speed = v }, true)} /></Field>
          {o.motion.waypoints.map((w, i) => (
            <div key={i} className="row" style={{ marginTop: 4 }}>
              <span className="xs muted" style={{ width: 24 }}>P{i + 1}</span>
              <Num value={w[0]} step={0.1} width={70} onChange={(v) => update((x) => { x.motion!.waypoints[i][0] = v }, true)} />
              <Num value={w[1]} step={0.1} width={70} onChange={(v) => update((x) => { x.motion!.waypoints[i][1] = v }, true)} />
              <button className="btn sm icon ghost" onClick={() => update((x) => { x.motion!.waypoints.splice(i, 1) })}><Trash2 size={12} /></button>
            </div>))}
          <button className="btn sm" style={{ marginTop: 6 }} onClick={() => update((x) => { x.motion!.waypoints.push([0, 0]) })}>Add patrol point</button>
        </Panel>)}
    </div>
  )
}
