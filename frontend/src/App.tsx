import {
  Bot, Boxes, BrainCircuit, CircuitBoard, Cpu, Download, Globe2, LayoutDashboard, Library, Link2, Moon, PlayCircle, Redo2,
  ShieldCheck, Sun, Undo2, Wrench,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { IssueSummary } from './components/ui'
import { useStore } from './store'
import type { Workspace } from './types'
import AiLab from './workspaces/AiLab'
import CadWorkspace from './workspaces/CadWorkspace'
import CircuitStudio from './workspaces/CircuitStudio'
import Dashboard from './workspaces/Dashboard'
import ExportWorkspace from './workspaces/ExportWorkspace'
import FirmwareWorkspace from './workspaces/FirmwareWorkspace'
import LibraryWorkspace from './workspaces/LibraryWorkspace'
import RobotDesigner from './workspaces/RobotDesigner'
import SimulationLab from './workspaces/SimulationLab'
import TwinWorkspace from './workspaces/TwinWorkspace'
import ValidationWorkspace from './workspaces/ValidationWorkspace'
import WorldBuilder from './workspaces/WorldBuilder'

const NAV: { id: Workspace; label: string; icon: ReactNode; needsProject?: boolean; section?: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} /> },
  { id: 'library', label: 'Component library', icon: <Library size={16} /> },
  { id: 'world', label: '3D world builder', icon: <Globe2 size={16} />, needsProject: true, section: 'Design' },
  { id: 'cad', label: 'Mechanical CAD', icon: <Boxes size={16} />, needsProject: true },
  { id: 'robot', label: 'Robot designer', icon: <Bot size={16} />, needsProject: true },
  { id: 'circuit', label: 'Circuit studio', icon: <CircuitBoard size={16} />, needsProject: true },
  { id: 'firmware', label: 'Firmware', icon: <Cpu size={16} />, needsProject: true },
  { id: 'twin', label: 'Digital twin', icon: <Link2 size={16} />, needsProject: true, section: 'Integrate' },
  { id: 'validation', label: 'Design validation', icon: <ShieldCheck size={16} />, needsProject: true },
  { id: 'sim', label: 'Simulation & nav lab', icon: <PlayCircle size={16} />, needsProject: true, section: 'Test' },
  { id: 'ai', label: 'AI & perception lab', icon: <BrainCircuit size={16} />, needsProject: true },
  { id: 'export', label: 'Import / export', icon: <Download size={16} />, needsProject: true, section: 'Build' },
]

export default function App() {
  const { workspace, setWorkspace, project, dirty, saving, issues, undo, redo, past, future, toasts, save, loadLibrary } = useStore()
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    try { return (localStorage.getItem('rv-theme') as 'dark' | 'light') || 'dark' } catch { return 'dark' }
  })
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('rv-theme', theme) } catch { /* storage unavailable */ }
  }, [theme])
  useEffect(() => { loadLibrary().catch(() => undefined) }, [loadLibrary])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo() }
      if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo() }
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo, save])

  const page = (() => {
    if (!project && NAV.find((n) => n.id === workspace)?.needsProject) return <Dashboard />
    switch (workspace) {
      case 'world': return <WorldBuilder />
      case 'cad': return <CadWorkspace />
      case 'robot': return <RobotDesigner />
      case 'circuit': return <CircuitStudio />
      case 'twin': return <TwinWorkspace />
      case 'firmware': return <FirmwareWorkspace />
      case 'sim': return <SimulationLab />
      case 'ai': return <AiLab />
      case 'library': return <LibraryWorkspace />
      case 'validation': return <ValidationWorkspace />
      case 'export': return <ExportWorkspace />
      default: return <Dashboard />
    }
  })()

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" width={22} height={22} alt="" />
          RoboVerse <small>Studio</small>
        </div>
        {project ? (
          <>
            <strong>{project.name}</strong>
            <span className="chip">{project.type}</span>
            <span className="muted xs">{saving ? 'Saving…' : dirty ? 'Unsaved changes' : 'All changes saved'}</span>
            <span className="spacer" />
            <button className="btn icon ghost" title="Undo (Ctrl+Z)" disabled={!past.length} onClick={undo}><Undo2 size={16} /></button>
            <button className="btn icon ghost" title="Redo (Ctrl+Shift+Z)" disabled={!future.length} onClick={redo}><Redo2 size={16} /></button>
            <button className="btn sm ghost" onClick={() => setWorkspace('validation')} title="Design validation">
              <IssueSummary issues={issues} />
            </button>
          </>
        ) : (
          <><span className="muted">Design. Connect. Simulate. Validate. Build.</span><span className="spacer" /></>
        )}
        <button className="btn icon ghost" title="Toggle theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>
      <nav className="sidebar">
        {NAV.map((n) => (
          <div key={n.id}>
            {n.section && <div className="nav-section">{n.section}</div>}
            <button className={`nav-item ${workspace === n.id ? 'active' : ''}`} disabled={n.needsProject && !project}
              style={n.needsProject && !project ? { opacity: 0.4, cursor: 'default' } : undefined}
              onClick={() => (!n.needsProject || project) && setWorkspace(n.id)}>
              {n.icon}{n.label}
            </button>
          </div>
        ))}
        <div className="nav-section">Tools</div>
        <div className="xs muted" style={{ padding: '0 10px' }}><Wrench size={11} /> API docs: <a href="/docs" target="_blank" rel="noreferrer">/docs</a></div>
      </nav>
      <main className="main">{page}</main>
      <div className="toasts">{toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}</div>
    </div>
  )
}
