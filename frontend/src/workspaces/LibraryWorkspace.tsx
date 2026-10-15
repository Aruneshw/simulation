import { ExternalLink, Search, Star, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmt, Panel, SupportBadge } from '../components/ui'
import { useStore } from '../store'
import type { Component } from '../types'

interface Item { id: string; name: string; category: string; manufacturer: string | null; part_number: string | null; support_status: string; favorite: boolean; verified: boolean; interfaces: string[]; version: string }
interface Lib { items: Item[]; stats: { total: number; by_status: Record<string, number>; by_category: Record<string, number>; library_version: string } }

export default function LibraryWorkspace() {
  const { toast } = useStore()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [favorites, setFavorites] = useState(false)
  const [lib, setLib] = useState<Lib | null>(null)
  const [sel, setSel] = useState<(Component & { versions: string[]; dependency_issues: string[] }) | null>(null)
  const load = () => api.get<Lib>('/api/library', { q, category, status, favorites: favorites || undefined }).then(setLib)
  useEffect(() => { const t = setTimeout(load, 150); return () => clearTimeout(t) }, [q, category, status, favorites]) // eslint-disable-line react-hooks/exhaustive-deps

  const importFile = async (f: File) => {
    try {
      if (f.name.endsWith('.csv')) {
        const fd = new FormData(); fd.append('file', f)
        const r = await api.post<{ imported: string[]; errors: string[] }>('/api/library/import/csv', fd)
        toast(r.errors.length ? 'error' : 'ok', `Imported ${r.imported.length}; ${r.errors.length} error(s)${r.errors[0] ? `: ${r.errors[0]}` : ''}`)
      } else {
        const data = JSON.parse(await f.text())
        const r = await api.post<{ imported: string[]; errors: Record<string, string[]> }>('/api/library/import', Array.isArray(data) ? data : [data])
        const n = Object.keys(r.errors).length
        toast(n ? 'error' : 'ok', `Imported ${r.imported.length} as "imported · unverified"; ${n} rejected${n ? `: ${Object.entries(r.errors)[0][1][0]}` : ''}`)
      }
      useStore.setState({ library: {} }); useStore.getState().loadLibrary(); load()
    } catch (e) { toast('error', (e as Error).message) }
  }

  return (
    <div className="split" style={{ gridTemplateColumns: '1fr 440px' }}>
      <div className="page">
        <div className="row" style={{ marginBottom: 10 }}>
          <h1>Component library</h1>
          {lib && <span className="muted">{lib.stats.total} components · v{lib.stats.library_version}</span>}
          <span className="spacer" />
          <label className="btn"><Upload size={14} />Import JSON / CSV<input type="file" accept=".json,.csv" hidden onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} /></label>
        </div>
        <div className="row wrap" style={{ marginBottom: 10 }}>
          <Search size={14} /><input placeholder="Search name, part number, tag…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
          <select value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>
            {lib && Object.keys(lib.stats.by_category).sort().map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')} ({lib.stats.by_category[c]})</option>)}</select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any support status</option>
            {lib && Object.keys(lib.stats.by_status).map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')} ({lib.stats.by_status[c]})</option>)}</select>
          <label className="row small"><input type="checkbox" checked={favorites} onChange={(e) => setFavorites(e.target.checked)} />Favorites</label>
        </div>
        <Panel bodyClass="">
          <table className="t">
            <thead><tr><th /><th>Component</th><th>Category</th><th>Manufacturer / part</th><th>Interfaces</th><th>Support</th></tr></thead>
            <tbody>{lib?.items.map((c) => (
              <tr key={c.id} className={`click ${sel?.id === c.id ? 'sel' : ''}`} onClick={() => api.get<typeof sel>(`/api/library/${c.id}`).then(setSel)}>
                <td><button className="btn sm icon ghost" title="Favorite" onClick={async (e) => { e.stopPropagation(); await api.post(`/api/library/${c.id}/favorite`, undefined, { on: !c.favorite }); load() }}>
                  <Star size={13} fill={c.favorite ? 'var(--warning)' : 'none'} color={c.favorite ? 'var(--warning)' : 'currentColor'} /></button></td>
                <td><strong>{c.name}</strong><div className="mono xs muted">{c.id} · v{c.version}</div></td>
                <td className="xs">{c.category.replace(/_/g, ' ')}</td>
                <td className="xs">{c.manufacturer ?? '—'}<div className="muted">{c.part_number}</div></td>
                <td className="xs">{c.interfaces.join(', ')}</td>
                <td><SupportBadge status={c.support_status} />{c.verified && <span className="badge good" style={{ marginLeft: 4 }}>verified source</span>}</td>
              </tr>))}</tbody>
          </table>
        </Panel>
      </div>
      <aside className="scroll" style={{ borderLeft: '1px solid var(--border)', background: 'var(--surface-1)', padding: 10 }}>
        {!sel ? <div className="empty">Select a component to see pins, ratings, provenance and model status.</div> : (
          <div className="col">
            <div><h2>{sel.name}</h2><div className="muted small">{sel.manufacturer} {sel.part_number}</div>
              <div className="row wrap" style={{ marginTop: 4 }}><SupportBadge status={sel.support_status} />{sel.sim_model && <span className="chip">{sel.sim_model}</span>}
                <span className="chip">versions: {sel.versions.join(', ')}</span>
                {sel.datasheet && <a href={sel.datasheet} target="_blank" rel="noreferrer" className="row xs"><ExternalLink size={12} />datasheet</a>}</div></div>
            {sel.description && <div className="small secondary">{sel.description}</div>}
            <Panel title="Ratings (with provenance)" bodyClass="">
              <table className="t"><tbody>{Object.entries(sel.ratings).map(([k, r]) => (
                <tr key={k}><td className="mono xs">{k}</td><td className="num">{r.value == null ? <span className="muted">unknown</span> : `${fmt(r.value, 3)} ${r.unit}`}</td>
                  <td><span className={`badge ${r.source === 'datasheet' ? 'good' : r.source === 'assumption' ? 'warning' : ''}`}>{r.source}</span>{r.note && <div className="xs muted">{r.note}</div>}</td></tr>))}</tbody></table>
            </Panel>
            <Panel title={`Pins (${sel.pins.length})`} bodyClass="">
              <div style={{ maxHeight: 280, overflow: 'auto' }}><table className="t"><thead><tr><th>Pin</th><th>Type</th><th>Electrical</th></tr></thead>
                <tbody>{sel.pins.map((p) => (
                  <tr key={p.id}><td className="mono xs">{p.id}</td><td className="xs">{p.type}</td>
                    <td className="xs secondary">{[p.v_min != null || p.v_max != null ? `${p.v_min ?? '?'}–${p.v_max ?? '?'} V` : '', p.v_nominal != null ? `${p.v_nominal} V out` : '',
                      p.logic_v != null ? `${p.logic_v} V logic` : '', p.vih_min != null ? `VIH ≥ ${p.vih_min.toFixed(2)} V` : '', p.v_abs_max != null ? `abs max ${p.v_abs_max} V` : '',
                      p.i_max != null ? `${p.i_max} A` : '', p.capabilities.join(' ')].filter(Boolean).join(' · ')}</td></tr>))}</tbody></table></div>
            </Panel>
            {sel.compatibility.length > 0 && <Panel title="Compatibility notes">{sel.compatibility.map((c) => <div key={c} className="small">• {c}</div>)}</Panel>}
            <Panel title="Provenance">
              <div className="small">Source: <strong>{sel.provenance.source}</strong> · {sel.provenance.verified ? 'verified against source' : 'not verified'}</div>
              <div className="small">License: {sel.provenance.license} · Author: {sel.provenance.author}</div>
              {sel.provenance.notes && <div className="xs muted">{sel.provenance.notes}</div>}
              {sel.footprint && <div className="xs">Footprint: <span className="mono">{sel.footprint}</span></div>}
              {sel.dependency_issues.map((d) => <div key={d} className="xs" style={{ color: 'var(--warning)' }}>{d}</div>)}
            </Panel>
          </div>)}
      </aside>
    </div>
  )
}
