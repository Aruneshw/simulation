import { Grid, OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { AlertTriangle, Download, Plus, Upload } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { api, download } from '../api'
import { Field, fmt, Num, Panel } from '../components/ui'
import { uid, useStore } from '../store'
import type { CadPart } from '../types'

interface PartReport {
  volume_m3: number; mass_kg: number; center_of_mass: number[]; inertia: number[]; bbox: number[][]; triangles: number; genus: number
  density: number; mesh: { positions: number[]; indices: number[] }; note: string
}
interface MeshImport { kind: string; editable: boolean; note: string; check: { watertight: boolean; triangles: number; open_edges: number; bbox_size: number[]; unit_hint: string }; mesh: { positions: number[]; indices: number[] } | null }

const MATERIALS = ['aluminium', 'steel', 'stainless', 'abs', 'pla', 'petg', 'nylon', 'acrylic', 'plywood', 'polyurethane', 'carbon_fiber', 'fr4']

function MeshView({ mesh, color }: { mesh: { positions: number[]; indices: number[] }; color: string }) {
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(mesh.positions, 3))
    g.setIndex(mesh.indices)
    g.computeVertexNormals()
    g.computeBoundingSphere()
    return g
  }, [mesh])
  const r = geo.boundingSphere?.radius ?? 0.1
  const c = geo.boundingSphere?.center ?? new THREE.Vector3()
  return (
    <group scale={0.3 / Math.max(r, 1e-3)} rotation={[-Math.PI / 2, 0, 0]}>
      <mesh geometry={geo} position={[-c.x, -c.y, -c.z]} castShadow>
        <meshStandardMaterial color={color} metalness={0.35} roughness={0.45} flatShading />
      </mesh>
    </group>
  )
}

export default function CadWorkspace() {
  const { project, edit, toast } = useStore()
  const parts = project!.cad.parts
  const [selId, setSelId] = useState(parts[0]?.id ?? '')
  const part = parts.find((p) => p.id === selId)
  const [rep, setRep] = useState<PartReport | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [imported, setImported] = useState<MeshImport | null>(null)
  const [asm, setAsm] = useState<{ interference: { a: string; b: string; volume_m3: number }[]; clearance: { a: string; b: string; aabb_gap_m: number }[]; errors: string[] } | null>(null)
  const idx = parts.findIndex((p) => p.id === selId)

  useEffect(() => {
    if (!part || part.kind !== 'parametric') { setRep(null); return }
    const t = setTimeout(() => api.post<PartReport>('/api/cad/part', part).then((r) => { setRep(r); setErr(null) }).catch((e) => setErr(e.message)), 250)
    return () => clearTimeout(t)
  }, [part])

  const newPart = (kind: 'box' | 'plate') => {
    const id = uid('part_')
    const p: CadPart = kind === 'box'
      ? { id, name: 'Bracket block', kind: 'parametric', material: 'aluminium', parameters: { x: 0.05, y: 0.03, z: 0.02, bore: 0.004 }, result: 'cut',
        features: [{ id: 'body', op: 'box', params: { x: '$x', y: '$y', z: '$z' }, operands: [] },
          { id: 'hole', op: 'cylinder', params: { h: 0.1, r: '$bore' }, operands: [] },
          { id: 'cut', op: 'difference', params: {}, operands: ['body', 'hole'] }] }
      : { id, name: 'Mount plate', kind: 'parametric', material: 'abs', parameters: { w: 0.1, h: 0.06, t: 0.003, r: 0.0016 },
        features: [{ id: 'plate', op: 'extrude', params: { height: '$t' }, operands: [], sketch: [
          { type: 'rect', params: { w: '$w', h: '$h' } }, { type: 'circle', params: { r: '$r', cx: '$w/2-0.008', cy: '$h/2-0.008' } },
          { type: 'circle', params: { r: '$r', cx: '-$w/2+0.008', cy: '-$h/2+0.008' } }] }] }
    edit((pr) => { pr.cad.parts.push(p) })
    setSelId(id)
  }

  const importMesh = async (f: File) => {
    const fd = new FormData(); fd.append('file', f); if (project!.id) fd.append('project_id', project!.id)
    try {
      const r = await api.post<MeshImport & { asset_id: string | null }>('/api/import/mesh', fd)
      setImported(r)
      const id = uid('mesh_')
      edit((pr) => { pr.cad.parts.push({ id, name: f.name, kind: 'imported_mesh', material: 'abs', parameters: {}, features: [], mesh_ref: r.asset_id }) })
      setSelId(id)
      toast('info', `Imported ${r.check.triangles} triangles (${r.check.watertight ? 'watertight' : 'NOT watertight'}). Meshes are not editable parametric solids.`)
    } catch (e) { toast('error', (e as Error).message) }
  }

  const checkAssembly = async () => setAsm(await api.post('/api/cad/assembly-check', project))

  return (
    <div className="split" style={{ gridTemplateColumns: '260px 1fr 340px' }}>
      <aside className="scroll" style={{ borderRight: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        <h4 style={{ marginBottom: 6 }}>Parts ({parts.length})</h4>
        {parts.map((p) => (
          <button key={p.id} className={`nav-item ${p.id === selId ? 'active' : ''}`} onClick={() => setSelId(p.id)}>
            {p.name}<span className={`badge ${p.kind === 'parametric' ? 'good' : 'warning'}`} style={{ marginLeft: 'auto' }}>{p.kind === 'parametric' ? 'parametric' : 'mesh'}</span>
          </button>))}
        <div className="row wrap" style={{ marginTop: 8 }}>
          <button className="btn sm" onClick={() => newPart('box')}><Plus size={13} />Block + bore</button>
          <button className="btn sm" onClick={() => newPart('plate')}><Plus size={13} />Sketch plate</button>
          <label className="btn sm"><Upload size={13} />Import STL/OBJ<input type="file" accept=".stl,.obj" hidden onChange={(e) => e.target.files?.[0] && importMesh(e.target.files[0])} /></label>
        </div>
        <hr className="sep" />
        <h4 style={{ marginBottom: 6 }}>Assembly ({project!.cad.assembly.length} placements)</h4>
        <table className="t"><tbody>{project!.cad.assembly.map((a) => (
          <tr key={a.id}><td className="xs">{a.id}</td><td className="xs muted">{a.part} → {a.link ?? '—'}</td></tr>))}</tbody></table>
        <button className="btn sm" style={{ marginTop: 6 }} onClick={checkAssembly}>Interference & clearance check</button>
        {asm && (
          <div className="col small" style={{ marginTop: 6 }}>
            {asm.interference.length === 0 ? <span className="badge good">no interference</span> : asm.interference.map((i) => (
              <div key={i.a + i.b} className="issue error"><strong>{i.a} ∩ {i.b}</strong>: {(i.volume_m3 * 1e9).toFixed(0)} mm³ overlap</div>))}
            {asm.clearance.slice(0, 6).map((c) => <div key={c.a + c.b} className="xs muted">{c.a} ↔ {c.b}: ≥ {(c.aabb_gap_m * 1000).toFixed(1)} mm (AABB)</div>)}
            {asm.errors.map((e) => <div key={e} className="xs" style={{ color: 'var(--warning)' }}>{e}</div>)}
          </div>)}
      </aside>

      <div className="viewport">
        {part?.kind === 'imported_mesh' && (
          <div className="overlay panel small" style={{ top: 10, left: 10, padding: 8, maxWidth: 420 }}>
            <AlertTriangle size={14} color="var(--warning)" /> Imported mesh — triangle geometry only, <strong>not an editable parametric solid</strong>. Use FreeCAD (STEP) for B-rep editing.
          </div>)}
        {err && <div className="overlay panel small" style={{ top: 10, left: 10, padding: 8, color: 'var(--critical)' }}>{err}</div>}
        <Canvas shadows camera={{ position: [0.7, 0.6, 0.9], fov: 40, near: 0.01 }}>
          <ambientLight intensity={0.55} /><directionalLight position={[2, 3, 2]} intensity={1.4} castShadow />
          <Grid args={[4, 4]} cellSize={0.05} sectionSize={0.25} position={[0, -0.25, 0]} infiniteGrid fadeDistance={4} cellColor="#3a4656" sectionColor="#52627a" />
          {part?.kind === 'parametric' && rep && <MeshView mesh={rep.mesh} color="#9aa8ba" />}
          {part?.kind === 'imported_mesh' && imported?.mesh && <MeshView mesh={imported.mesh} color="#c9a26b" />}
          <OrbitControls makeDefault />
        </Canvas>
      </div>

      <aside className="scroll" style={{ borderLeft: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        {part && (
          <div className="col">
            <Panel title={part.name}>
              <div className="fields">
                <Field label="Name"><input value={part.name} onChange={(e) => edit((p) => { p.cad.parts[idx].name = e.target.value }, { merge: true })} /></Field>
                <Field label="Material"><select value={part.material} onChange={(e) => edit((p) => { p.cad.parts[idx].material = e.target.value })}>{MATERIALS.map((m) => <option key={m}>{m}</option>)}</select></Field>
                {part.kind === 'parametric' && <h4>Parametric dimensions</h4>}
                {Object.entries(part.parameters).map(([k, v]) => (
                  <Field key={k} label={k}><Num value={v} step={0.001} unit="m" onChange={(nv) => edit((p) => { p.cad.parts[idx].parameters[k] = nv }, { merge: true })} /></Field>))}
              </div>
            </Panel>
            {part.kind === 'parametric' && (
              <Panel title="Feature tree">
                {part.features.map((f) => (
                  <div key={f.id} className="row xs" style={{ padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                    <span className="chip">{f.op}</span><span className="mono">{f.id}</span>
                    <span className="muted">{f.operands.length ? `(${f.operands.join(', ')})` : f.sketch ? `${f.sketch.length} sketch shapes` : ''}</span>
                    {part.result === f.id && <span className="badge good">result</span>}
                  </div>))}
                <div className="xs muted" style={{ marginTop: 6 }}>Built with the Manifold kernel (extrude, union, difference, intersection). Fillets, chamfers and STEP need the FreeCAD adapter.</div>
              </Panel>)}
            {rep && (
              <Panel title="Mass properties">
                <table className="t"><tbody>
                  <tr><td className="secondary">Volume</td><td className="num">{(rep.volume_m3 * 1e6).toFixed(3)} cm³</td></tr>
                  <tr><td className="secondary">Mass ({rep.density} kg/m³)</td><td className="num">{(rep.mass_kg * 1000).toFixed(2)} g</td></tr>
                  <tr><td className="secondary">Centre of mass</td><td className="num mono xs">{rep.center_of_mass.map((c) => (c * 1000).toFixed(2)).join(', ')} mm</td></tr>
                  <tr><td className="secondary">Ixx, Iyy, Izz</td><td className="num mono xs">{rep.inertia.slice(0, 3).map((c) => c.toExponential(3)).join(', ')} kg·m²</td></tr>
                  <tr><td className="secondary">Bounding box</td><td className="num mono xs">{rep.bbox[1].map((h, i) => ((h - rep.bbox[0][i]) * 1000).toFixed(1)).join(' × ')} mm</td></tr>
                  <tr><td className="secondary">Triangles / genus</td><td className="num">{rep.triangles} / {rep.genus}</td></tr>
                </tbody></table>
                <div className="xs muted" style={{ marginTop: 4 }}>{rep.note}</div>
                <div className="row" style={{ marginTop: 8 }}>
                  <button className="btn sm" onClick={() => download('stl', project!, { part: part.id })}><Download size={13} />STL</button>
                  <button className="btn sm" onClick={() => download('obj', project!, { part: part.id })}><Download size={13} />OBJ</button>
                </div>
              </Panel>)}
            {part.kind === 'imported_mesh' && imported && (
              <Panel title="Mesh check">
                <div className="small">Watertight: <strong>{imported.check.watertight ? 'yes' : 'no'}</strong> · open edges {imported.check.open_edges}</div>
                <div className="small">Size: {imported.check.bbox_size.map((s) => fmt(s, 3)).join(' × ')} {imported.check.unit_hint === 'mm?' && <span className="badge warning">large — was this exported in mm?</span>}</div>
                <div className="xs muted" style={{ marginTop: 4 }}>{imported.note}</div>
              </Panel>)}
          </div>)}
      </aside>
    </div>
  )
}
