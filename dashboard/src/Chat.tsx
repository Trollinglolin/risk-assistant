import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUp, CaretRight, Key, Wrench } from '@phosphor-icons/react'
import { ApiError, STATIC, api, examples, getStoredKey, setStoredKey, type AgentResult, type PortfolioId } from './api'

const SUGGESTIONS = [
  "What's my 99% VaR and what drove it this week?",
  'Which holding contributes most to my expected shortfall?',
  'Is GARCH VaR above or below historical right now?',
  'What happens if the Hang Seng falls 20%?',
  'Does the Student-t model pass Kupiec over 5 years?',
]

type Turn =
  | { kind: 'q'; text: string }
  | { kind: 'a'; result: AgentResult }
  | { kind: 'err'; text: string; status?: number }

export function Chat({ pf }: { pf: PortfolioId }) {
  return STATIC ? <RecordedChat pf={pf} /> : <LiveChat pf={pf} />
}

/** Static (GitHub Pages) build: no backend, so show answers the live agent gave earlier. */
function RecordedChat({ pf }: { pf: PortfolioId }) {
  const [list, setList] = useState<AgentResult[] | null>(null)
  const [open, setOpen] = useState<number | null>(0)
  useEffect(() => { examples().then(setList).catch(() => setList([])) }, [])
  return (
    <section className="flex h-full min-h-[520px] flex-col rounded-lg border border-line bg-surface">
      <header className="border-b border-line px-5 py-4">
        <h2 className="text-[15px] font-semibold">Risk assistant: recorded answers</h2>
        <p className="mt-0.5 text-[13px] text-muted">
          This hosted copy has no backend, so the chat is off. These are real answers from the live
          agent (every number comes from an engine tool call), recorded on the 9-name book. Run the
          project locally to ask your own questions.
        </p>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {pf !== 'core' && <p className="text-[13px] text-muted">Recorded on the Core 9 book.</p>}
        {list === null && <div className="skeleton h-3 w-2/3" />}
        {list?.map((r, i) => (
          <div key={i}>
            <button onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}
              className="w-full rounded-md border border-line bg-raised px-3 py-2 text-left text-[13px] text-ink-2 hover:border-accent hover:text-ink">
              {r.question}
            </button>
            {open === i && <div className="mt-3"><Answer r={r} /></div>}
          </div>
        ))}
      </div>
    </section>
  )
}

function LiveChat({ pf }: { pf: PortfolioId }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  // hosted build: no dev proxy adds the key, so ask for it up front
  const [needKey, setNeedKey] = useState(import.meta.env.PROD && !getStoredKey())
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [turns, busy])

  async function send(q: string) {
    const question = q.trim()
    if (question.length < 3 || busy) return
    setText('')
    setTurns((t) => [...t, { kind: 'q', text: question }])
    setBusy(true)
    try {
      const result = await api.ask(question, pf)
      setTurns((t) => [...t, { kind: 'a', result }])
    } catch (e) {
      const status = e instanceof ApiError ? e.status : undefined
      if (status === 401) setNeedKey(true)
      setTurns((t) => [...t, { kind: 'err', status, text: explain(e as Error, status) }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="flex h-full min-h-[520px] flex-col rounded-lg border border-line bg-surface">
      <header className="border-b border-line px-5 py-4">
        <h2 className="text-[15px] font-semibold">Ask the risk assistant</h2>
        <p className="mt-0.5 text-[13px] text-muted">
          The model only calls the engine's tools. Every number below comes from a tool result.
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4" aria-live="polite">
        {turns.length === 0 && (
          <div>
            <p className="text-[13px] text-ink-2">Try one of these:</p>
            <ul className="mt-2 space-y-1.5">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button onClick={() => send(s)}
                    className="w-full rounded-md border border-line bg-raised px-3 py-2 text-left text-[13px] text-ink-2 transition-colors hover:border-accent hover:text-ink active:translate-y-px">
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((t, i) =>
          t.kind === 'q' ? (
            <div key={i} className="ml-8 rounded-lg bg-accent-soft px-3 py-2 text-[14px] text-ink">{t.text}</div>
          ) : t.kind === 'a' ? (
            <Answer key={i} r={t.result} />
          ) : (
            <div key={i} role="alert" className="rounded-md border border-line px-3 py-2 text-[13px] text-critical">{t.text}</div>
          ),
        )}
        {busy && (
          <div className="space-y-2" aria-label="Waiting for the model">
            <div className="skeleton h-3 w-2/3" /><div className="skeleton h-3 w-1/2" />
          </div>
        )}
        <div ref={end} />
      </div>

      {needKey && <KeyField onSave={() => setNeedKey(false)} />}

      <form onSubmit={(e: FormEvent) => { e.preventDefault(); send(text) }} className="border-t border-line p-3">
        <label htmlFor="ask" className="sr-only">Question</label>
        <div className="flex items-end gap-2 rounded-md border border-line bg-raised px-3 py-2 focus-within:border-accent">
          <textarea id="ask" rows={2} value={text} maxLength={2000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text) } }}
            placeholder="Ask about VaR, contributions, stress tests or backtests"
            className="min-h-[40px] flex-1 resize-none bg-transparent text-[14px] text-ink outline-none placeholder:text-muted" />
          <button type="submit" disabled={busy || text.trim().length < 3} aria-label="Send"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-accent text-white transition disabled:opacity-40 active:scale-[0.97]">
            <ArrowUp size={16} weight="bold" />
          </button>
        </div>
      </form>
    </section>
  )
}

function Answer({ r }: { r: AgentResult }) {
  return (
    <div>
      {r.tool_calls.length > 0 && (
        <ul className="mb-2 space-y-1">
          {r.tool_calls.map((c, i) => (
            <li key={i}>
              <details className="group rounded-md border border-line bg-raised">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-[12.5px]">
                  <CaretRight size={12} className="text-muted transition-transform group-open:rotate-90" />
                  <Wrench size={14} className={c.is_error ? 'text-critical' : 'text-accent'} />
                  <span className="num text-ink">{c.name}</span>
                  <span className="num truncate text-muted">{argsLine(c.input)}</span>
                </summary>
                <pre className="num max-h-56 overflow-auto border-t border-line px-2.5 py-2 text-[11.5px] leading-relaxed text-ink-2">
                  {JSON.stringify(c.output, null, 2)}
                </pre>
              </details>
            </li>
          ))}
        </ul>
      )}
      <Markdownish text={r.answer} />
      <p className="num mt-2 text-[11.5px] text-muted">
        {r.model} · {r.tool_calls.length} tool call{r.tool_calls.length === 1 ? '' : 's'} · {r.input_tokens + r.output_tokens} tokens · {r.latency_s.toFixed(1)}s
      </p>
    </div>
  )
}

function KeyField({ onSave }: { onSave: () => void }) {
  const [k, setK] = useState(getStoredKey())
  return (
    <form className="flex items-center gap-2 border-t border-line px-3 py-2"
      onSubmit={(e) => { e.preventDefault(); setStoredKey(k.trim()); onSave() }}>
      <Key size={16} className="text-muted" />
      <label htmlFor="key" className="text-[13px] text-ink-2" title="The assistant uses a rate-limited LLM quota, so it needs an access key. The risk panels are open to everyone.">Access key</label>
      <input id="key" type="password" value={k} onChange={(e) => setK(e.target.value)}
        className="flex-1 rounded border border-line bg-raised px-2 py-1 text-[13px] text-ink outline-none focus:border-accent" />
      <button className="rounded-md border border-line px-2.5 py-1 text-[13px] text-ink hover:border-accent">Save</button>
    </form>
  )
}

/** Minimal rendering for the model's markdown: paragraphs, bullets, **bold**, `code`. */
function Markdownish({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/)
  return (
    <div className="space-y-2 text-[14px] leading-relaxed text-ink">
      {blocks.map((b, i) => {
        const lines = b.split('\n')
        if (lines.every((l) => /^\s*[-*] /.test(l)))
          return <ul key={i} className="list-disc space-y-0.5 pl-5">{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[-*] /, ''))}</li>)}</ul>
        return <p key={i}>{lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l)}</span>)}</p>
      })}
    </div>
  )
}

function inline(s: string) {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith('**') ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
      : part.startsWith('`') ? <code key={i} className="num rounded bg-raised px-1 text-[13px]">{part.slice(1, -1)}</code>
        : part.replace(/\$\\?alpha\s*=\s*([\d.]+)\$/g, 'alpha = $1').replace(/\$\\nu\$/g, 'ν'),
  )
}

function argsLine(input: Record<string, unknown>) {
  const parts = Object.entries(input).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
  return parts.length ? `(${parts.join(', ')})` : '()'
}

function explain(e: Error, status?: number) {
  if (status === 503) return 'The agent is switched off: set HKRISK_API_KEY in .env and restart the API.'
  if (status === 401) return 'The API rejected the key. Enter the HKRISK_API_KEY value below.'
  if (status === 429) return `Rate limit reached. ${e.message}`
  if (e.message.includes('Failed to fetch')) return 'Cannot reach the API. Is uvicorn running?'
  return e.message
}
