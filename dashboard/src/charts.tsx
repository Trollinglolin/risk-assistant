import { useMemo } from 'react'
import {
  Bar, BarChart, CartesianGrid, ComposedChart, LabelList, Line, ResponsiveContainer,
  Scatter, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { BacktestSeries, Compare, Contributions } from './api'
import { METHOD_LABEL, fmtHKD, fmtK, fmtPct, nameOf } from './api'

const axisTick = { fill: 'var(--muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }
const tooltipBox = 'rounded-md border border-line bg-raised px-3 py-2 text-[12.5px] shadow-sm'

/* ---------------- VaR backtest: forecast vs realised loss ---------------- */

interface BtRow { date: string; loss: number; var: number; breach: number | null }

export function BacktestChart({ s }: { s: BacktestSeries }) {
  const rows = useMemo<BtRow[]>(
    () => s.dates.map((d, i) => ({ date: d, loss: s.loss[i], var: s.var[i], breach: s.exception[i] ? s.loss[i] : null })),
    [s],
  )
  const years = useMemo(() => {
    const seen = new Set<string>()
    // one tick per calendar year, at its first January trading day (skips a partial first year)
    return rows.filter((r) => { const y = r.date.slice(0, 4); if (seen.has(y) || r.date.slice(5, 7) !== '01') return false; seen.add(y); return true }).map((r) => r.date)
  }, [rows])

  return (
    <div>
      <Legend
        items={[
          { kind: 'line', color: 'var(--accent)', label: 'VaR forecast' },
          { kind: 'bar', color: 'var(--neutral-mark)', label: 'Realised loss (gain below 0)' },
          { kind: 'dot', color: 'var(--critical)', label: 'Breach: loss above VaR' },
        ]}
      />
      <div className="h-[300px] w-full">
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap={0}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="date" ticks={years} tickFormatter={(d: string) => d.slice(0, 4)} tick={axisTick}
              axisLine={{ stroke: 'var(--axis)' }} tickLine={false} interval={0} />
            <YAxis tickFormatter={fmtK} tick={axisTick} axisLine={false} tickLine={false} width={48} />
            <Tooltip content={<BtTooltip />} cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }} isAnimationActive={false} />
            <Bar dataKey="loss" fill="var(--neutral-mark)" isAnimationActive={false} />
            <Line dataKey="var" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Scatter dataKey="breach" fill="var(--critical)" stroke="var(--surface)" strokeWidth={2}
              shape="circle" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function BtTooltip({ active, payload }: { active?: boolean; payload?: { payload: BtRow }[] }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  return (
    <div className={tooltipBox}>
      <div className="num text-muted">{r.date}</div>
      <div className="mt-1 grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <span className="text-ink-2">VaR</span><span className="num text-right text-ink">{fmtHKD(r.var)}</span>
        <span className="text-ink-2">{r.loss >= 0 ? 'Loss' : 'Gain'}</span>
        <span className="num text-right text-ink">{fmtHKD(Math.abs(r.loss))}</span>
      </div>
      {r.breach != null && <div className="mt-1 font-medium text-critical">Breach</div>}
    </div>
  )
}

/* ---------------- Component VaR by holding ---------------- */

export function ContributionChart({ c, top = 12 }: { c: Contributions; top?: number }) {
  const sorted = [...c.components].sort((a, b) => b.component - a.component)
  const head = sorted.slice(0, top)
  const rest = sorted.slice(top)
  const rows = [
    ...head.map((r) => ({ ...r, name: nameOf(r.ticker) })),
    ...(rest.length ? [{
      ticker: `${rest.length} others`, name: `${rest.length} others`,
      position_value: rest.reduce((a, r) => a + r.position_value, 0),
      component: rest.reduce((a, r) => a + r.component, 0),
      pct_of_total: rest.reduce((a, r) => a + r.pct_of_total, 0),
    }] : []),
  ]
  return (
    <div className="w-full" style={{ height: rows.length * 34 + 8 }}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 92, bottom: 0, left: 0 }} barCategoryGap={6}>
          <XAxis type="number" hide domain={[(min: number) => Math.min(0, min), 'dataMax']} />
          <YAxis type="category" dataKey="name" width={112} tick={{ fill: 'var(--ink-2)', fontSize: 13 }}
            axisLine={false} tickLine={false} />
          <Tooltip cursor={{ fill: 'var(--accent-soft)' }} isAnimationActive={false}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const r = payload[0].payload as (typeof rows)[number]
              return (
                <div className={tooltipBox}>
                  <div className="font-medium text-ink">{r.name} <span className="num text-muted">{r.ticker}</span></div>
                  <div className="num mt-1 text-ink-2">Component {fmtHKD(r.component)} ({fmtPct(r.pct_of_total, 1)})</div>
                  <div className="num text-ink-2">Position {fmtHKD(r.position_value)}</div>
                </div>
              )
            }} />
          <Bar dataKey="component" fill="var(--accent)" radius={[0, 4, 4, 0]} isAnimationActive={false}>
            <LabelList dataKey="component" position="right"
              content={(p) => {
                const { x = 0, y = 0, width = 0, height = 0, index = 0 } = p as Record<string, number>
                const r = rows[index]
                return (
                  <text x={Number(x) + Math.max(Number(width), 0) + 6} y={Number(y) + Number(height) / 2} dy={4}
                    fill="var(--ink-2)" fontSize={12} fontFamily="var(--font-mono)">
                    {fmtK(r.component)} · {fmtPct(r.pct_of_total, 0)}
                  </text>
                )
              }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ---------------- VaR and ES by method ---------------- */

export function MethodChart({ c, selected }: { c: Compare; selected: string }) {
  const rows = c.ranked_by_var_desc.map((r) => ({ ...r, label: METHOD_LABEL[r.method] }))
  return (
    <div>
      <Legend items={[
        { kind: 'bar', color: 'var(--accent)', label: 'VaR' },
        { kind: 'bar', color: 'var(--series-2)', label: 'Expected shortfall' },
      ]} />
      <div className="w-full" style={{ height: rows.length * 52 + 8 }}>
        <ResponsiveContainer>
          <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }} barGap={2} barCategoryGap={10}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="label" width={92} axisLine={false} tickLine={false}
              tick={(p) => {
                const label = String(p.payload?.value ?? '')
                const on = rows.find((r) => r.label === label)?.method === selected
                return (
                  <text x={Number(p.x)} y={Number(p.y)} dy={4} textAnchor="end" fontSize={13}
                    fill={on ? 'var(--ink)' : 'var(--ink-2)'} fontWeight={on ? 600 : 400}>{label}</text>
                )
              }} />
            <Tooltip cursor={{ fill: 'var(--accent-soft)' }} isAnimationActive={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const r = payload[0].payload as (typeof rows)[number]
                return (
                  <div className={tooltipBox}>
                    <div className="font-medium text-ink">{r.label}</div>
                    <div className="num mt-1 text-ink-2">VaR {fmtHKD(r.var)}</div>
                    <div className="num text-ink-2">ES {r.es == null ? 'undefined (tail index ≥ 1)' : fmtHKD(r.es)}</div>
                  </div>
                )
              }} />
            <Bar dataKey="var" fill="var(--accent)" radius={[0, 4, 4, 0]} isAnimationActive={false}>
              <LabelList dataKey="var" position="right" formatter={(v) => fmtK(Number(v))}
                style={{ fill: 'var(--ink-2)', fontSize: 12, fontFamily: 'var(--font-mono)' }} />
            </Bar>
            <Bar dataKey="es" fill="var(--series-2)" radius={[0, 4, 4, 0]} isAnimationActive={false}>
              <LabelList dataKey="es" position="right" formatter={(v) => (v == null ? '' : fmtK(Number(v)))}
                style={{ fill: 'var(--ink-2)', fontSize: 12, fontFamily: 'var(--font-mono)' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/* ---------------- shared legend ---------------- */

function Legend({ items }: { items: { kind: 'line' | 'bar' | 'dot'; color: string; label: string }[] }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          {i.kind === 'line' && <span className="inline-block h-[2px] w-4 rounded" style={{ background: i.color }} />}
          {i.kind === 'bar' && <span className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ background: i.color }} />}
          {i.kind === 'dot' && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: i.color }} />}
          {i.label}
        </li>
      ))}
    </ul>
  )
}
