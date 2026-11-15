import { useEffect, useState, type ReactNode } from 'react'
import { WarningCircle } from '@phosphor-icons/react'

export type Async<T> = { data?: T; error?: Error; loading: boolean }

/** Fetch on mount and whenever deps change; ignores stale responses. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [state, setState] = useState<Async<T>>({ loading: true })
  useEffect(() => {
    let live = true
    setState((s) => ({ data: s.data, loading: true }))
    fn().then(
      (data) => live && setState({ data, loading: false }),
      (error: Error) => live && setState({ error, loading: false }),
    )
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

export function Panel({ title, note, action, children, className = '' }: {
  title: string; note?: ReactNode; action?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      <header className="flex items-start justify-between gap-4 px-5 pt-4">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {note && <p className="mt-0.5 text-[13px] text-muted">{note}</p>}
        </div>
        {action}
      </header>
      <div className="px-5 pb-5 pt-3">{children}</div>
    </section>
  )
}

export function Skeleton({ h = 16, w = '100%' }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} />
}

export function ErrorNote({ error }: { error: Error }) {
  const offline = error.message.includes('Failed to fetch') || error.message.includes('NetworkError')
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-line bg-raised px-3 py-2.5 text-[13px] text-ink-2">
      <WarningCircle size={18} weight="bold" className="mt-px shrink-0 text-critical" />
      <span>
        {offline
          ? 'Cannot reach the API. Start it with: uv run uvicorn hkrisk.api.main:app'
          : error.message}
      </span>
    </div>
  )
}

/** Shows skeleton while the first load is in flight, the error if it failed, else children. */
export function Load<T>({ q, h = 200, children }: { q: Async<T>; h?: number; children: (d: T) => ReactNode }) {
  if (q.error) return <ErrorNote error={q.error} />
  if (!q.data) return <Skeleton h={h} />
  return <div className={q.loading ? 'opacity-60 transition-opacity' : 'transition-opacity'}>{children(q.data)}</div>
}

export function Segmented<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line bg-raised p-0.5">
      {options.map((o) => {
        const on = o.value === value
        return (
          <button
            key={String(o.value)}
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`rounded-[5px] px-2.5 py-1 text-[13px] transition-colors ${
              on ? 'bg-accent-soft font-medium text-accent-ink' : 'text-ink-2 hover:text-ink'
            }`}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Stat({ label, value, sub, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'critical' | 'warn'
}) {
  const toneCls = tone === 'good' ? 'text-good' : tone === 'critical' ? 'text-critical' : tone === 'warn' ? 'text-warn' : 'text-ink'
  return (
    <div className="min-w-0">
      <div className="text-[13px] text-muted">{label}</div>
      <div className={`num mt-1 text-[22px] font-medium leading-tight ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-[12.5px] text-ink-2">{sub}</div>}
    </div>
  )
}
