import { useEffect, useState } from 'react'
import { CheckCircle, Moon, Sun, WarningCircle, XCircle } from '@phosphor-icons/react'
import {
  METHODS, METHOD_LABEL, PORTFOLIOS, api, fmtHKD, fmtPct, fmtSigned, nameOf, rememberNames,
  type BacktestSummary, type Method, type PortfolioId,
} from './api'
import { BacktestChart, ContributionChart, MethodChart } from './charts'
import { Chat } from './Chat'
import { Load, Panel, Segmented, Skeleton, Stat, useAsync } from './ui'

const ALPHAS = [
  { value: 0.95, label: '95%' },
  { value: 0.975, label: '97.5%' },
  { value: 0.99, label: '99%' },
]

export default function App() {
  const [pf, setPf] = useState<PortfolioId>(() => (new URLSearchParams(location.search).get('portfolio') === 'hsi' ? 'hsi' : 'core'))
  const [method, setMethod] = useState<Method>('historical')
  const [alpha, setAlpha] = useState(0.99)

  const portfolio = useAsync(() => api.portfolio(pf), [pf])
  if (portfolio.data) rememberNames(portfolio.data.positions)
  const risk = useAsync(() => api.risk(pf, method, alpha), [pf, method, alpha])
  const compare = useAsync(() => api.compare(pf, alpha), [pf, alpha])
  const bt = useAsync(() => api.backtest(pf, method, alpha), [pf, method, alpha])
  const series = useAsync(() => api.backtestSeries(pf, method, alpha), [pf, method, alpha])
  const contribMethod = method === 'normal' ? 'normal' : 'historical'
  const contrib = useAsync(() => api.contributions(pf, contribMethod, alpha), [pf, contribMethod, alpha])
  const explain = useAsync(() => api.explain(pf, alpha), [pf, alpha])

  return (
    <div className="mx-auto max-w-[1440px] px-4 pb-12 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-4 py-5">
        <div>
          <h1 className="text-[20px] font-semibold tracking-tight">HK equity risk</h1>
          <p className="text-[13px] text-muted">
            {portfolio.data
              ? <>{portfolio.data.label}: {portfolio.data.n_positions} Hong Kong holdings, valued at close on <span className="num">{portfolio.data.as_of}</span>. 1-day horizon, 500-day window.</>
              : 'Loading portfolio'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="Portfolio" value={pf} onChange={setPf}
            options={PORTFOLIOS.map((p) => ({ value: p.value, label: p.label }))} />
          <Segmented label="VaR method" value={method} onChange={setMethod}
            options={METHODS.map((m) => ({ value: m, label: METHOD_LABEL[m] }))} />
          <Segmented label="Confidence" value={alpha} onChange={setAlpha} options={ALPHAS} />
          <ThemeToggle />
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <main className="min-w-0 space-y-4">
          {/* headline numbers */}
          <section className="grid grid-cols-2 gap-x-6 gap-y-5 rounded-lg border border-line bg-surface px-5 py-4 md:grid-cols-4">
            {risk.error ? <div className="col-span-full"><Load q={risk}>{() => null}</Load></div> : risk.data ? (
              <>
                <Stat label="Portfolio value (HKD)" value={fmtHKD(risk.data.portfolio_value)} sub={`as of ${risk.data.as_of}`} />
                <Stat label={`${fmtPct(alpha, alpha === 0.975 ? 1 : 0)} VaR (HKD)`} value={fmtHKD(risk.data.var)}
                  sub={`${fmtPct(risk.data.var_pct)} of value, ${METHOD_LABEL[method]}`} />
                <Stat label="Expected shortfall (HKD)" value={fmtHKD(risk.data.es)}
                  sub={risk.data.es_pct == null ? 'undefined: tail index ≥ 1' : `${fmtPct(risk.data.es_pct)} of value`} />
                <BacktestStat b={bt.data} loading={!bt.data && !bt.error} />
              </>
            ) : [0, 1, 2, 3].map((i) => <div key={i} className="space-y-2"><Skeleton h={12} w="60%" /><Skeleton h={26} w="80%" /></div>)}
          </section>

          <Panel title="Backtest: forecast VaR against the next day's loss"
            note={bt.data
              ? `${bt.data.start} to ${bt.data.end}, ${bt.data.days} trading days, fitted each day on the prior 500 days.`
              : 'Out-of-sample, full available history.'}>
            <Load q={series} h={330}>{(s) => <BacktestChart s={s} />}</Load>
            {bt.data && <BacktestFacts b={bt.data} />}
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel title="What drives the risk"
              note={`Component ${fmtPct(alpha, alpha === 0.975 ? 1 : 0)} VaR by holding (Euler), ${contribMethod} model. Sums to total VaR.`}>
              {method !== contribMethod && (
                <p className="mb-2 text-[12.5px] text-ink-2">Component VaR is available for the historical and normal models; showing historical.</p>
              )}
              <Load q={contrib} h={310}>{(c) => <ContributionChart c={c} top={12} />}</Load>
            </Panel>
            <Panel title="Model comparison" note="Same portfolio and window, five ways to model the tail.">
              <Load q={compare} h={290}>{(c) => <MethodChart c={c} selected={method} />}</Load>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <Panel title="Why VaR moved this week" note="Historical VaR change split into its two causes.">
              <Load q={explain} h={180}>{(e) => (
                <div>
                  <dl className="grid grid-cols-[1fr_auto] gap-y-2 text-[14px] [&_dd]:num">
                    <dt className="text-ink-2">VaR on {e.start_date}</dt><dd className="text-right">{fmtHKD(e.var_start)}</dd>
                    <dt className="text-ink-2">Price and position moves</dt><dd className="text-right">{fmtSigned(e.price_position_effect)}</dd>
                    <dt className="text-ink-2">Old days leaving the window</dt><dd className="text-right">{fmtSigned(e.window_roll_effect)}</dd>
                    <dt className="border-t border-line pt-2 font-medium">VaR on {e.end_date}</dt>
                    <dd className="border-t border-line pt-2 text-right font-medium">{fmtHKD(e.var_end)}</dd>
                  </dl>
                  <p className="mt-3 text-[12.5px] text-ink-2">
                    Biggest change by holding: {[...e.position_deltas].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 2)
                      .map((d) => `${nameOf(d.ticker)} ${fmtSigned(d.delta)}`).join(', ')}.
                  </p>
                </div>
              )}</Load>
            </Panel>
            <StressPanel pf={pf} />
          </div>

          <Panel title="Holdings" note={portfolio.data && portfolio.data.n_positions > 12
              ? 'Sorted by value. Names listed after 2020 show the date their real price history starts; earlier returns are beta x Hang Seng.'
              : undefined}>
            <Load q={portfolio} h={240}>{(p) => (<Holdings p={p} />)}</Load>
          </Panel>
        </main>

        <aside className="xl:sticky xl:top-4 xl:h-[calc(100dvh-2rem)]">
          <Chat pf={pf} />
        </aside>
      </div>
    </div>
  )
}

function BacktestStat({ b, loading }: { b?: BacktestSummary; loading: boolean }) {
  if (loading || !b) return <div className="space-y-2"><Skeleton h={12} w="60%" /><Skeleton h={26} w="80%" /></div>
  const zone = b.latest_250d.zone
  const Icon = zone === 'green' ? CheckCircle : zone === 'yellow' ? WarningCircle : XCircle
  return (
    <Stat label="Basel traffic light, last 250 days"
      value={<span className="inline-flex items-center gap-1.5 font-sans capitalize"><Icon size={20} weight="fill" />{zone}</span>}
      tone={zone === 'green' ? 'good' : zone === 'yellow' ? 'warn' : 'critical'}
      sub={`${b.latest_250d.count} breaches, capital multiplier ${b.latest_250d.multiplier.toFixed(2)}`} />
  )
}

function BacktestFacts({ b }: { b: BacktestSummary }) {
  const items = [
    { label: 'Breaches', value: `${b.exceptions}`, sub: `expected ${b.expected.toFixed(1)}` },
    { label: 'Kupiec coverage p', value: b.kupiec_p.toFixed(3), pass: b.kupiec_pass },
    { label: 'Christoffersen independence p', value: b.christoffersen_ind_p.toFixed(3), pass: b.christoffersen_ind_p >= 0.05 },
    { label: 'Conditional coverage p', value: b.christoffersen_cc_p.toFixed(3), pass: b.christoffersen_cc_pass },
  ]
  return (
    <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 md:grid-cols-4">
      {items.map((i) => (
        <div key={i.label}>
          <dt className="text-[12.5px] text-muted">{i.label}</dt>
          <dd className="num mt-0.5 flex items-center gap-1.5 text-[16px]">
            {i.value}
            {'pass' in i && (i.pass
              ? <span className="inline-flex items-center gap-1 font-sans text-[12.5px] text-good"><CheckCircle size={14} weight="fill" />pass</span>
              : <span className="inline-flex items-center gap-1 font-sans text-[12.5px] text-critical"><XCircle size={14} weight="fill" />reject</span>)}
            {i.sub && <span className="font-sans text-[12.5px] text-muted">{i.sub}</span>}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function StressPanel({ pf }: { pf: PortfolioId }) {
  const results = useAsync(async () => {
    const list = (await api.scenarios()).scenarios
    return Promise.all(list.map(async (s) => ({ s, r: await api.stress(pf, s.name) })))
  }, [pf])
  const [shock, setShock] = useState(-20)
  const [debounced, setDebounced] = useState(shock)
  useEffect(() => { const t = setTimeout(() => setDebounced(shock), 250); return () => clearTimeout(t) }, [shock])
  const hsi = useAsync(() => api.hsiShock(pf, debounced / 100), [pf, debounced])

  return (
    <Panel title="Stress tests" note="Today's holdings through past crashes. Stocks not yet listed are proxied by beta to the Hang Seng.">
      <Load q={results} h={150}>{(rows) => (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-[13.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[12.5px] text-muted">
                <th className="py-2 font-normal">Scenario</th>
                <th className="py-2 pl-4 text-right font-normal">Hang Seng</th>
                <th className="py-2 pl-4 text-right font-normal">P&amp;L (HKD)</th>
                <th className="py-2 pl-4 text-right font-normal">Portfolio</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ s, r }) => {
                const proxiedAll = r.positions.filter((p) => p.proxied).map((p) => nameOf(p.ticker))
                const proxied = proxiedAll.length > 4 ? [...proxiedAll.slice(0, 3), `${proxiedAll.length - 3} more`] : proxiedAll
                return (
                  <tr key={s.name} className="align-top">
                    <td className="py-2">
                      <div>{s.description.split(':')[0]}</div>
                      <div className="num text-[12px] text-muted">{s.start} to {s.end}</div>
                      {proxied.length > 0 && <div className="text-[12px] text-muted">Proxied: {proxied.join(', ')}</div>}
                    </td>
                    <td className="num whitespace-nowrap py-2 pl-4 text-right">{fmtPct(s.hsi_drawdown, 1)}</td>
                    <td className="num whitespace-nowrap py-2 pl-4 text-right">{fmtSigned(r.total_pnl)}</td>
                    <td className="num whitespace-nowrap py-2 pl-4 text-right font-medium">{fmtPct(r.total_pnl_pct, 1)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}</Load>

      <div className="mt-4 border-t border-line pt-4">
        <label htmlFor="shock" className="flex items-baseline justify-between text-[13px] text-ink-2">
          <span>Hypothetical Hang Seng move</span>
          <span className="num text-ink">{shock > 0 ? '+' : ''}{shock}%</span>
        </label>
        <input id="shock" type="range" min={-50} max={30} step={1} value={shock}
          onChange={(e) => setShock(Number(e.target.value))}
          className="mt-2 w-full accent-[var(--accent)]" />
        <div className="mt-1 text-[13.5px]">
          {hsi.error ? <span className="text-critical">{hsi.error.message}</span> : hsi.data ? (
            <span className={hsi.loading ? 'opacity-60' : ''}>
              Portfolio P&amp;L <span className="num font-medium">{fmtSigned(hsi.data.total_pnl)}</span> HKD
              (<span className="num">{fmtPct(hsi.data.total_pnl_pct, 1)}</span>), using each holding's beta to the index.
            </span>
          ) : <Skeleton h={14} w="70%" />}
        </div>
      </div>
    </Panel>
  )
}

function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    try {
      const saved = new URLSearchParams(location.search).get('theme') ?? localStorage.getItem('hkrisk-theme')
      if (saved === 'light' || saved === 'dark') return saved
    } catch { /* storage blocked */ }
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('hkrisk-theme', theme) } catch { /* ignore */ }
  }, [theme])
  return (
    <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      className="grid h-8 w-8 place-items-center rounded-md border border-line bg-raised text-ink-2 hover:text-ink">
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  )
}

function Holdings({ p }: { p: import('./api').Portfolio }) {
  const [all, setAll] = useState(false)
  const rows = all ? p.positions : p.positions.slice(0, 12)
  const proxiedCol = p.positions.some((x) => x.history_proxied_before)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[600px] text-[13.5px]">
        <thead>
          <tr className="border-b border-line text-left text-[12.5px] text-muted">
            <th className="py-2 font-normal">Holding</th>
            {proxiedCol && <th className="py-2 font-normal">Sector</th>}
            <th className="py-2 text-right font-normal">Shares</th>
            <th className="py-2 text-right font-normal">Value (HKD)</th>
            <th className="py-2 text-right font-normal">Weight</th>
            {proxiedCol && <th className="py-2 text-right font-normal">Real history from</th>}
          </tr>
        </thead>
        <tbody className="num">
          {rows.map((x) => (
            <tr key={x.ticker}>
              <td className="py-1.5 font-sans">{nameOf(x.ticker)} <span className="num text-muted">{x.ticker}</span></td>
              {proxiedCol && <td className="py-1.5 font-sans text-ink-2">{x.sector?.split(' ')[0].replace(',', '')}</td>}
              <td className="py-1.5 text-right">{fmtHKD(x.shares)}</td>
              <td className="py-1.5 text-right">{fmtHKD(x.value)}</td>
              <td className="py-1.5 text-right">{fmtPct(x.weight, 1)}</td>
              {proxiedCol && (
                <td className="py-1.5 text-right text-muted">
                  {x.history_proxied_before && x.history_proxied_before > '2020' ? x.history_proxied_before : ''}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {p.positions.length > 12 && (
        <button onClick={() => setAll(!all)}
          className="mt-3 rounded-md border border-line px-3 py-1.5 text-[13px] text-ink-2 hover:border-accent hover:text-ink">
          {all ? 'Show top 12' : `Show all ${p.positions.length}`}
        </button>
      )}
    </div>
  )
}
