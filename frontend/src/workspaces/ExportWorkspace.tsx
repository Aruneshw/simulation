import { Download, FileArchive, Upload } from 'lucide-react'
import { useState } from 'react'
import { api, download } from '../api'
import { IssueList, Panel } from '../components/ui'
import { useStore } from '../store'
import type { Issue } from '../types'

const GROUPS: { title: string; items: [string, string, string][] }[] = [
  { title: 'Project', items: [['package', 'RoboVerse package (.rvproj)', 'Versioned manifest, checksums, project model, all generated artifacts, original assets, recent run results']] },
  { title: 'Robot & simulation', items: [
    ['urdf', 'URDF', 'With ros2_control block; preserved unsupported elements re-emitted'], ['xacro', 'Xacro', 'Parameterised wheel geometry'],
    ['sdf', 'SDF 1.9', 'Gazebo model with sensors and DiffDrive plugin'], ['world_sdf', 'Gazebo world (SDF)', 'Environment with collision geometry'],
    ['mjcf', 'MuJoCo MJCF', 'Model used by the MuJoCo backend'], ['ros2', 'ROS 2 package (.zip)', 'Description, launch files, ros2_control and Nav2 parameters']] },
  { title: 'Electronics', items: [['spice', 'SPICE netlist (.cir)', 'Supported subset; unsupported parts listed as comments'], ['kicad', 'KiCad netlist (.net)', 'Import into Pcbnew for footprint placement and routing']] },
  { title: 'Embedded', items: [['firmware', 'PlatformIO project (.zip)', 'Generated controller + HIL serial protocol']] },
]

export default function ExportWorkspace() {
  const { project, toast, open } = useStore()
  const [checks, setChecks] = useState<Issue[] | null>(null)
  const [report, setReport] = useState<{ warnings: string[]; skipped: string[] } | null>(null)

  const preExport = async () => {
    const r = await api.post<{ issues: Issue[] }>('/api/validate', project, { stage: 'pre_export' })
    setChecks(r.issues.filter((i) => i.severity !== 'info' || i.domain === 'export'))
  }
  const run = async (fmt: string) => {
    try {
      const rep = await download(fmt, project!)
      if (rep) setReport(rep)
      toast('ok', `Exported ${fmt}`)
    } catch (e) { toast('error', (e as Error).message) }
  }
  const importPkg = async (f: File) => {
    const fd = new FormData(); fd.append('file', f)
    try {
      const r = await api.post<{ project_id: string; report: { errors: string[]; warnings: string[]; preserved_files: string[] } }>('/api/import/package', fd)
      toast(r.report.errors.length ? 'error' : 'ok', `Imported as a new project. ${r.report.errors.length} integrity error(s), ${r.report.preserved_files.length} extra file(s) preserved.`)
      await open(r.project_id)
    } catch (e) { toast('error', (e as Error).message) }
  }

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 12 }}>
        <div><h1>Import & export</h1><div className="muted">Original sources are preserved; conversions report anything they cannot represent instead of dropping it.</div></div>
        <span className="spacer" />
        <label className="btn"><Upload size={14} />Import .rvproj<input type="file" accept=".rvproj,.zip" hidden onChange={(e) => e.target.files?.[0] && importPkg(e.target.files[0])} /></label>
        <button className="btn" onClick={preExport}>Run pre-export checks</button>
      </div>
      <div className="grid" style={{ gridTemplateColumns: '1fr 380px', alignItems: 'start' }}>
        <div className="col">
          {GROUPS.map((g) => (
            <Panel key={g.title} title={g.title} bodyClass="">
              <table className="t"><tbody>{g.items.map(([fmt, label, desc]) => (
                <tr key={fmt}><td style={{ width: 230 }}><strong>{label}</strong></td><td className="secondary small">{desc}</td>
                  <td style={{ width: 110 }}><button className="btn sm" onClick={() => run(fmt)}>{fmt === 'package' ? <FileArchive size={13} /> : <Download size={13} />}Export</button></td></tr>))}</tbody></table>
            </Panel>))}
          <Panel title="Imports available in workspaces">
            <div className="small secondary">URDF → Robot designer · STL/OBJ meshes → Mechanical CAD (flagged non-parametric) · component JSON/CSV → Library · CSV telemetry → per-run download in the Simulation lab.</div>
            <div className="xs muted" style={{ marginTop: 4 }}>STEP and native KiCad schematics require the FreeCAD and KiCad adapters; they are reported as unavailable on the Dashboard when not installed.</div>
          </Panel>
        </div>
        <div className="col">
          {report && (
            <Panel title="Last package export report">
              {[...report.warnings, ...report.skipped].length === 0 ? <div className="small">Nothing was skipped.</div>
                : [...report.warnings, ...report.skipped].map((w) => <div key={w} className="xs" style={{ color: 'var(--warning)' }}>• {w}</div>)}
            </Panel>)}
          {checks && <Panel title="Pre-export checks"><IssueList issues={checks} compact /></Panel>}
        </div>
      </div>
    </div>
  )
}
