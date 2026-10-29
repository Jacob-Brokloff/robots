import { useEffect, useRef, useState } from 'react'
import { captureViewport, type Box } from './capture'
import { labelOf, selectorOf } from './selector'

/** Where the Pages Function lives (functions/feedback-api/issue.ts). Not under /api: demo mode answers those. */
const ENDPOINT = '/feedback-api/issue'
const NAME_KEY = 'feedback.name'
/** A drag shorter than this is a click: the box becomes the element under the pointer. */
const CLICK_PX = 6

type Mode = 'closed' | 'note' | 'pointing' | 'pointed' | 'sending' | 'sent'

function storedName(): string {
  try { return localStorage.getItem(NAME_KEY) ?? '' } catch { return '' }
}
function storeName(name: string): void {
  try { localStorage.setItem(NAME_KEY, name) } catch { /* private window: the name is just not remembered */ }
}

/** The page element under a point, skipping the widget's own overlay. */
function elementAt(root: Element, x: number, y: number): Element | null {
  return document.elementsFromPoint(x, y).find(el => !root.contains(el) && el !== document.documentElement) ?? null
}

function boxOf(el: Element): Box {
  const r = el.getBoundingClientRect()
  return { x: r.left, y: r.top, w: r.width, h: r.height }
}

export default function Feedback({ root }: { root: Element }) {
  const [mode, setMode] = useState<Mode>('closed')
  const [note, setNote] = useState('')
  const [name, setName] = useState(storedName)
  const [shot, setShot] = useState(true)
  const [hp, setHp] = useState('')
  const [error, setError] = useState('')
  const [issueUrl, setIssueUrl] = useState('')
  const [box, setBox] = useState<Box | null>(null)
  const [hover, setHover] = useState<Box | null>(null)
  const target = useRef<Element | null>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  const pointedFrom = useRef<'point' | 'note'>('note')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && mode !== 'sending') reset() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode])

  function reset() {
    setMode('closed'); setBox(null); setHover(null); setError(''); target.current = null; drag.current = null
  }

  function startPointing() {
    setError(''); setBox(null); setHover(null); target.current = null; setMode('pointing')
  }

  function onDown(e: React.PointerEvent) {
    drag.current = { x: e.clientX, y: e.clientY }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }

  function onMove(e: React.PointerEvent) {
    const start = drag.current
    if (!start) {
      const el = elementAt(root, e.clientX, e.clientY)
      setHover(el ? boxOf(el) : null)
      return
    }
    setHover(null)
    setBox({
      x: Math.min(start.x, e.clientX), y: Math.min(start.y, e.clientY),
      w: Math.abs(e.clientX - start.x), h: Math.abs(e.clientY - start.y),
    })
  }

  function onUp(e: React.PointerEvent) {
    const start = drag.current
    drag.current = null
    if (!start) return
    const dragged = Math.abs(e.clientX - start.x) > CLICK_PX || Math.abs(e.clientY - start.y) > CLICK_PX
    if (dragged) {
      const b = { x: Math.min(start.x, e.clientX), y: Math.min(start.y, e.clientY),
        w: Math.abs(e.clientX - start.x), h: Math.abs(e.clientY - start.y) }
      setBox(b)
      target.current = elementAt(root, b.x + b.w / 2, b.y + b.h / 2)
    } else {
      const el = elementAt(root, e.clientX, e.clientY)
      target.current = el
      setBox(el ? boxOf(el) : null)
    }
    setHover(null)
    pointedFrom.current = 'point'
    setMode('pointed')
  }

  async function send() {
    if (!note.trim()) { setError('Add a note first.'); return }
    const pointed = mode === 'pointed'
    setError(''); setMode('sending')
    storeName(name.trim())
    try {
      const shots = shot ? await captureViewport(root, pointed ? box : null) : { full: '', closeup: '' }
      const el = pointed ? target.current : null
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: pointed ? 'point' : 'note',
          note: note.trim(),
          name: name.trim(),
          website: hp,
          url: location.href,
          selector: el ? selectorOf(el) : '',
          element: labelOf(el),
          box: pointed ? box : null,
          viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 },
          scheme: document.documentElement.dataset.scheme
            ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark (OS)' : 'paper (OS)'),
          userAgent: navigator.userAgent,
          branch: import.meta.env.VITE_PAGES_BRANCH ?? '',
          commit: import.meta.env.VITE_PAGES_COMMIT ?? '',
          screenshot: shots.full,
          closeup: shots.closeup,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || `the server answered ${res.status}`)
      setIssueUrl(data.issue_url ?? '')
      setNote(''); setBox(null); target.current = null
      setMode('sent')
    } catch (err) {
      setError(`Not sent: ${err instanceof Error ? err.message : String(err)}`)
      setMode(pointed ? 'pointed' : 'note')
    }
  }

  const form = (
    <form className="fb-form" onSubmit={e => { e.preventDefault(); void send() }}>
      <textarea
        autoFocus
        className="fb-input"
        rows={4}
        maxLength={4000}
        placeholder={mode === 'pointed' ? 'What should change here?' : 'What should change? Ideas, bugs, anything.'}
        value={note}
        onChange={e => setNote(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send() }}
      />
      <input className="fb-input" placeholder="Your name (optional)" maxLength={60} value={name}
        onChange={e => setName(e.target.value)} />
      {/* Honeypot: hidden from people, filled in by form-spamming bots. */}
      <input className="fb-hp" tabIndex={-1} autoComplete="off" aria-hidden="true" name="website"
        value={hp} onChange={e => setHp(e.target.value)} />
      <label className="fb-check">
        <input type="checkbox" checked={shot} onChange={e => setShot(e.target.checked)} /> Include a screenshot
      </label>
      {error && <p className="fb-error" role="alert">{error}</p>}
      <div className="fb-row">
        <button type="button" className="fb-btn" onClick={reset}>Cancel</button>
        <button type="submit" className="fb-btn fb-primary">Send</button>
      </div>
      <p className="fb-fine">Posted as a public GitHub issue. Ctrl+Enter sends.</p>
    </form>
  )

  if (mode === 'sending') return <div className="fb-toast" role="status">Sending feedback...</div>

  return (
    <>
      {mode === 'pointing' && (
        <div className="fb-overlay" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}>
          <div className="fb-hint">
            Click what should change, or drag a box around it. Esc cancels.
            {/* Its own pointer handlers stop here, so pressing it does not start a box. */}
            <button type="button" className="fb-link" autoFocus onPointerDown={e => e.stopPropagation()}
              onPointerUp={e => e.stopPropagation()} onClick={() => { setHover(null); setMode('note') }}>
              General note instead
            </button>
          </div>
          {hover && <div className="fb-box fb-hover" style={{ left: hover.x, top: hover.y, width: hover.w, height: hover.h }} />}
          {box && <div className="fb-box" style={{ left: box.x, top: box.y, width: box.w, height: box.h }} />}
        </div>
      )}

      {mode === 'pointed' && (
        <>
          {box && <div className="fb-box fb-fixed" style={{ left: box.x, top: box.y, width: box.w, height: box.h }} />}
          <div className="fb-panel" role="dialog" aria-label="Feedback on this spot"
            style={popoverPlace(box)}>
            <div className="fb-head">
              <strong>Feedback on this spot</strong>
              <button type="button" className="fb-link" onClick={startPointing}>Point again</button>
            </div>
            {form}
          </div>
        </>
      )}

      {mode === 'note' && (
        <div className="fb-panel fb-dock" role="dialog" aria-label="Send feedback">
          <div className="fb-head"><strong>Send feedback</strong></div>
          <button type="button" className="fb-btn fb-wide" onClick={startPointing}>
            Point at something on the page
          </button>
          {form}
        </div>
      )}

      {mode === 'sent' && (
        <div className="fb-panel fb-dock" role="status">
          <div className="fb-head"><strong>Thanks, sent.</strong></div>
          {issueUrl && <p className="fb-fine"><a href={issueUrl} target="_blank" rel="noreferrer">See it on GitHub</a></p>}
          <div className="fb-row">
            <button type="button" className="fb-btn" onClick={reset}>Close</button>
            <button type="button" className="fb-btn fb-primary" onClick={() => setMode('note')}>Send more</button>
          </div>
        </div>
      )}

      {(mode === 'closed' || mode === 'sent') && (
        <div className="fb-launch">
          {/* Feedback starts by pointing, since most notes are about one spot. The hint offers a general note. */}
          <button type="button" className="fb-fab fb-main" onClick={startPointing}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M4 3l7 17 2.5-7L20 10.5z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            </svg>
            Feedback
          </button>
        </div>
      )}
    </>
  )
}

/** Puts the note form beside the box: below it when there is room, else above, kept on screen. */
function popoverPlace(box: Box | null): React.CSSProperties {
  const W = 320
  const H = 300
  if (!box) return { right: 16, bottom: 16 }
  const left = Math.max(8, Math.min(box.x, window.innerWidth - W - 8))
  const below = box.y + box.h + 10
  const top = below + H < window.innerHeight ? below : Math.max(8, box.y - H - 10)
  return { left, top }
}
