import { useMemo, useRef, useState } from 'react'

export interface Series { key: string; label: string; color: string; values: (number | null)[] }

/** Time-series line chart: one y-axis, 2px lines, crosshair + tooltip, legend for >= 2 series
 *  with direct end labels. Colors carry identity only; text stays in text tokens. */
export function LineChart({ title, unit, t, series, height = 120, yMin, yMax, digits = 2 }: {
  title: string; unit?: string; t: number[]; series: Series[]; height?: number; yMin?: number; yMax?: number; digits?: number
}) {
  const ref = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const W = 360
  const pad = { l: 40, r: series.length > 1 ? 44 : 10, t: 6, b: 18 }
  const { lo, hi, t0, t1 } = useMemo(() => {
    let lo = Infinity
    let hi = -Infinity
    for (const s of series) for (const v of s.values) if (v !== null && Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1 }
    if (yMin !== undefined) lo = Math.min(lo, yMin)
    if (yMax !== undefined) hi = Math.max(hi, yMax)
    if (hi - lo < 1e-9) { hi += 0.5; lo -= 0.5 }
    const span = hi - lo
    return { lo: lo - span * 0.05, hi: hi + span * 0.05, t0: t[0] ?? 0, t1: Math.max(t[t.length - 1] ?? 1, (t[0] ?? 0) + 1e-6) }
  }, [series, t, yMin, yMax])
  const x = (v: number) => pad.l + ((v - t0) / (t1 - t0)) * (W - pad.l - pad.r)
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (height - pad.t - pad.b)
  const ticks = [lo, (lo + hi) / 2, hi]

  const path = (vals: (number | null)[]) => {
    let d = ''
    let pen = false
    vals.forEach((v, i) => {
      if (v === null || !Number.isFinite(v)) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(t[i]).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return d
  }

  const onMove = (e: React.MouseEvent) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !t.length) return
    const px = ((e.clientX - r.left) / r.width) * W
    const tv = t0 + ((px - pad.l) / (W - pad.l - pad.r)) * (t1 - t0)
    let best = 0
    for (let i = 0; i < t.length; i++) if (Math.abs(t[i] - tv) < Math.abs(t[best] - tv)) best = i
    setHover(best)
  }

  return (
    <div className="col" style={{ gap: 2 }}>
      <div className="row xs">
        <strong className="secondary">{title}</strong>{unit && <span className="muted">({unit})</span>}
        <span className="spacer" />
        {series.length > 1 && (
          <span className="legend">{series.map((s) => <span key={s.key}><span className="swatch" style={{ background: s.color }} />{s.label}</span>)}</span>
        )}
      </div>
      <div style={{ position: 'relative' }}>
        <svg ref={ref} viewBox={`0 0 ${W} ${height}`} width="100%" height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)}
          role="img" aria-label={`${title} chart`}>
          {ticks.map((v, i) => (
            <g key={i}>
              <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="var(--grid)" strokeWidth={1} />
              <text x={pad.l - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill="var(--text-muted)">{v.toFixed(Math.abs(hi - lo) < 2 ? 2 : 1)}</text>
            </g>
          ))}
          <text x={pad.l} y={height - 4} fontSize={9} fill="var(--text-muted)">{t0.toFixed(0)} s</text>
          <text x={W - pad.r} y={height - 4} fontSize={9} fill="var(--text-muted)" textAnchor="end">{t1.toFixed(0)} s</text>
          {series.map((s) => <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
          {series.length > 1 && endLabels(series, y, height - pad.b).map((l) => (
            <text key={l.key} x={W - pad.r + 4} y={l.y + 3} fontSize={9} fill="var(--text-secondary)">{l.label}</text>))}
          {hover !== null && (
            <g>
              <line x1={x(t[hover])} x2={x(t[hover])} y1={pad.t} y2={height - pad.b} stroke="var(--text-muted)" strokeDasharray="3 3" />
              {series.map((s) => {
                const v = s.values[hover]
                return v == null ? null : <circle key={s.key} cx={x(t[hover])} cy={y(v)} r={4} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
              })}
            </g>
          )}
        </svg>
        {hover !== null && (
          <div className="panel xs" style={{ position: 'absolute', top: 0, left: `${Math.min(70, (x(t[hover]) / W) * 100)}%`, padding: '4px 7px', pointerEvents: 'none', whiteSpace: 'nowrap' }}>
            <div className="muted">t = {t[hover].toFixed(2)} s</div>
            {series.map((s) => (
              <div key={s.key}><span className="swatch" style={{ background: s.color }} />{s.label}: <strong>{s.values[hover] == null ? '—' : (s.values[hover] as number).toFixed(digits)}</strong>{unit ? ` ${unit}` : ''}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** Direct end-of-line labels, pushed apart so they never overlap (min 10 px). */
function endLabels(series: Series[], y: (v: number) => number, bottom: number) {
  const out = series.map((s) => {
    const last = [...s.values].reverse().find((v) => v !== null && Number.isFinite(v))
    return last == null ? null : { key: s.key, label: s.label, y: y(last) }
  }).filter((l): l is { key: string; label: string; y: number } => l !== null).sort((a, b) => a.y - b.y)
  for (let i = 1; i < out.length; i++) if (out[i].y - out[i - 1].y < 10) out[i].y = out[i - 1].y + 10
  const over = out.length ? out[out.length - 1].y - bottom : 0
  if (over > 0) out.forEach((l) => { l.y -= over })
  return out
}
