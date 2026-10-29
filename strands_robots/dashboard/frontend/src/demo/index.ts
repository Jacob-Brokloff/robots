/**
 * Demo mode: the whole dashboard with no server and no robots behind it.
 *
 * Built only when VITE_DEMO=1 (`npm run build:preview`, the per-PR preview deploy). main.tsx
 * imports this module behind that flag, so a normal build, the one the Python package ships
 * under static/, carries none of it.
 *
 * It swaps the page's `fetch` and `WebSocket` for in-browser stand-ins before React mounts:
 * - GETs answer with responses captured from a real dashboard (captured.json) and the demo fleet
 * - the mesh socket streams that fleet, the camera sockets stream drawn frames (camera.ts)
 * - the handful of buttons a reviewer will press (stop, run, e-stop, teleop) change the demo
 *   state; every other write answers with a plain "demo build" refusal
 * Nothing leaves the browser: there is no host to send it to.
 */
import captured from './captured.json'
import { cameraFrame } from './camera'
import {
  activity, activityListeners, fleet, logActivity, LEADER, ROBOT, safety, snapshot, tasks, teleop,
} from './fleet'
import { BUNDLE_ROUTES } from '../lib/bundleRoutes.generated'

const REFUSAL = 'This is a demo build: no server or robot is behind this page, so nothing was sent.'
const routes = captured.routes as Record<string, unknown>
const nowS = () => Date.now() / 1000

/* ------------------------------ HTTP ------------------------------ */

type Handler = (m: RegExpMatchArray, body: any, url: URL) => unknown | Promise<unknown>

class Status {
  constructor(readonly status: number, readonly body: unknown) {}
}

/** Responses shaped like the server's (routes_mesh, routes_devices), for the writes a reviewer tries. */
const WRITES: Array<[RegExp, Handler]> = [
  [/^\/api\/robots\/([^/]+)\/stop$/, m => {
    const peer = decodeURIComponent(m[1])
    delete tasks[peer]
    logActivity({ source: 'api', action: 'stop', target: peer, ok: true })
    return { peer_id: peer, state: 'stopped', detail: '', result: { type: 'response', responder_id: peer,
      result: { status: 'success', content: [{ text: `Stopped on '${peer}' (demo)` }] }, timestamp: nowS() } }
  }],
  [/^\/api\/robots\/([^/]+)\/task$/, (m, body) => {
    const peer = decodeURIComponent(m[1])
    if (safety.locked) return new Status(409, { error: 'the fleet is e-stopped: resume it first (demo)' })
    const instruction = String(body?.instruction ?? 'demo task')
    tasks[peer] = { instruction, until: nowS() + 20 }
    logActivity({ source: 'api', action: 'task', target: peer, ok: true, detail: instruction })
    return { peer_id: peer, routed_to: peer, mirrored_to_twin: false, ok: true, timeout_s: 15,
      result: { type: 'response', responder_id: peer,
        result: { status: 'success', content: [{ text: `Policy started on '${peer}' (demo, async)` }] }, timestamp: nowS() } }
  }],
  [/^\/api\/robots\/([^/]+)\/reset$/, m => {
    const peer = decodeURIComponent(m[1])
    return { peer_id: peer, routed_to: peer, ok: true, result: { type: 'response', responder_id: peer,
      result: { status: 'success', content: [{ text: 'Reset to initial state (demo).' }] }, timestamp: nowS() } }
  }],
  [/^\/api\/robots\/([^/]+)\/ping$/, m => ({ thing: decodeURIComponent(m[1]), verdict: 'answered', reason: null, latency_ms: 42 })],
  [/^\/api\/robots\/([^/]+)\/teleop\/receive$/, m => {
    teleop.following = true
    logActivity({ source: 'api', action: 'teleop_receive', target: decodeURIComponent(m[1]), ok: true, detail: `following ${LEADER}` })
    return { ok: true }
  }],
  [/^\/api\/robots\/([^/]+)\/teleop\/(stop|publish)$/, (m) => {
    if (m[2] === 'stop' && decodeURIComponent(m[1]) !== LEADER) teleop.following = false
    return { ok: true }
  }],
  [/^\/api\/(mesh\/)?safety\/estop$/, () => {
    safety.locked = true
    safety.since = nowS()
    for (const id of Object.keys(tasks)) delete tasks[id]
    const ids = Object.keys(fleet())
    broadcast({ type: 'safety', kind: 'estop', data: { by: 'demo' } })
    broadcast(snapshot())
    logActivity({ source: 'estop', action: 'estop', target: 'fleet', ok: true, detail: `${ids.length} peers stopped (demo)` })
    return { targeted: ids, stale_skipped: [], counts: { stopped: ids.length, not_stopped: 0, no_answer: 0 }, all_stopped: true,
      stopped: Object.fromEntries(ids.map(id => [id, { state: 'stopped', detail: '' }])), not_stopped: {}, no_answer: [],
      lockout: { state: 'locked', reason: 'an e-stop from this dashboard (demo)', since: safety.since, by: 'demo' }, frozen: [] }
  }],
  [/^\/api\/(mesh\/)?safety\/resume$/, () => {
    safety.locked = false
    broadcast({ type: 'safety', kind: 'resume', data: { by: 'demo' } })
    broadcast(snapshot())
    logActivity({ source: 'estop', action: 'resume', target: 'fleet', ok: true, detail: 'demo' })
    return { lockout: { state: 'clear', reason: 'resumed (demo)', since: nowS(), by: 'demo' }, thawed: [], resumed: Object.keys(fleet()) }
  }],
  [/^\/api\/auth\/renew$/, () => ({ renewed: false })],
]

const READS: Array<[RegExp, Handler]> = [
  [/^\/openapi\.json$/, () => ({ openapi: '3.1.0', paths: Object.fromEntries(BUNDLE_ROUTES.map(r => [r, { get: {} }])) })],
  [/^\/api\/fleet$/, () => snapshot()],
  [/^\/api\/activity$/, (_m, _b, url) => ({ activity: activity.slice(0, Number(url.searchParams.get('limit') ?? 200)) })],
  [/^\/api\/safety$/, () => ({ scope: "this dashboard's simulation",
    lockout: safety.locked ? { state: 'locked', reason: 'an e-stop from this dashboard (demo)', since: safety.since, by: 'demo' }
      : { state: 'unknown', reason: 'no e-stop or resume seen since this dashboard started' } })],
  [/^\/api\/robots\/([^/]+)\/teleop$/, m => {
    const peer = decodeURIComponent(m[1])
    if (peer === LEADER) {
      return { peer_id: peer, result: { ok: true }, health: { receivers: {}, worst: null,
        publishers: { leader: { state: 'publishing', headline: '1832 frames at 30.0Hz', detail: null } } } }
    }
    if (peer === ROBOT && teleop.following) {
      const following = { state: 'following', headline: `following ${LEADER}`, detail: 'frames applied at 30 Hz, none refused' }
      return { peer_id: peer, result: { ok: true }, health: { receivers: { [LEADER]: following }, publishers: {}, worst: following } }
    }
    return { peer_id: peer, result: { ok: true }, health: { receivers: {}, publishers: {}, worst: null } }
  }],
  [/^\/api\/robots\/([^/]+)\/policy-fit$/, (m, _b, url) => {
    const peer = fleet()[decodeURIComponent(m[1])]
    const joints = Object.keys(peer?.state?.joints ?? {})
    return { ok: true, blocking: false, problems: [], checked: [], evidence: false, repo_id: url.searchParams.get('repo_id'),
      policy_type: null, robot: { joints, cameras: peer?.presence?.cameras ?? [] } }
  }],
  [/^\/api\/devices\/logs\/([^/]+)$/, m => ({ peer_id: decodeURIComponent(m[1]), alive: true,
    lines: ['demo build: robot logs are not recorded here'] })],
  [/^\/api\/checkpoints\/search$/, () => routes['/api/checkpoints/search']],
]

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

async function answer(method: string, url: URL, rawBody: unknown): Promise<Response> {
  const path = url.pathname
  let body: any = null
  if (typeof rawBody === 'string' && rawBody) { try { body = JSON.parse(rawBody) } catch { body = rawBody } }
  const table = method === 'GET' || method === 'HEAD' ? READS : WRITES
  for (const [rx, handler] of table) {
    const m = path.match(rx)
    if (!m) continue
    const out = await handler(m, body, url)
    return out instanceof Status ? json(out.status, out.body) : json(200, out)
  }
  if ((method === 'GET' || method === 'HEAD') && path in routes) return json(200, routes[path])
  if (method !== 'GET' && method !== 'HEAD') return json(503, { error: REFUSAL })
  return json(404, { error: `${path} has no demo data` })
}

/* ---------------------------- WebSocket ---------------------------- */

const meshSockets = new Set<DemoSocket>()

function broadcast(ev: unknown): void {
  for (const s of meshSockets) s.deliver(JSON.stringify(ev))
}

// Every activity row the demo logs also goes out on the mesh socket, as the server's does.
activityListeners.push(data => broadcast({ type: 'activity', data }))

class DemoSocket extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSING = 2
  readonly CLOSED = 3

  readonly url: string
  readonly protocol = ''
  readonly extensions = ''
  readonly bufferedAmount = 0
  binaryType: BinaryType = 'blob'
  readyState = 0
  onopen: ((ev: Event) => unknown) | null = null
  onmessage: ((ev: MessageEvent) => unknown) | null = null
  onclose: ((ev: CloseEvent) => unknown) | null = null
  onerror: ((ev: Event) => unknown) | null = null
  private timers: ReturnType<typeof setInterval>[] = []

  constructor(url: string | URL) {
    super()
    this.url = String(url)
    setTimeout(() => this.start(), 30)
  }

  private fire(type: 'open' | 'message' | 'close' | 'error', ev: Event): void {
    this.dispatchEvent(ev)
    const handler = this[`on${type}`] as ((e: Event) => unknown) | null
    handler?.call(this, ev)
  }

  deliver(data: string | Blob): void {
    if (this.readyState !== 1) return
    if (data instanceof Blob && this.binaryType === 'arraybuffer') {
      void data.arrayBuffer().then(buf => this.fire('message', new MessageEvent('message', { data: buf })))
      return
    }
    this.fire('message', new MessageEvent('message', { data }))
  }

  private every(ms: number, fn: () => void): void {
    this.timers.push(setInterval(fn, ms))
  }

  private start(): void {
    if (this.readyState !== 0) return
    this.readyState = 1
    this.fire('open', new Event('open'))
    const path = new URL(this.url, location.href).pathname
    const camera = path.match(/^\/ws\/camera\/([^/]+)\/([^/]+)$/)
    if (path.endsWith('/mesh')) this.mesh()
    else if (camera) this.camera(decodeURIComponent(camera[1]), decodeURIComponent(camera[2]))
    else if (path.endsWith('/voice')) this.close(1000, 'voice is not part of the demo')
    // the agent socket stays open and answers in send()
  }

  private mesh(): void {
    meshSockets.add(this)
    this.deliver(JSON.stringify(snapshot()))
    // 5 Hz, the rate the Pi publishes joints at (deploy/pi): faster only costs the page renders.
    this.every(200, () => {
      for (const p of Object.values(fleet())) {
        if (p.state) this.deliver(JSON.stringify({ type: 'state', peer_id: p.peer_id, data: p.state }))
      }
    })
    this.every(1000, () => {
      for (const p of Object.values(fleet())) {
        this.deliver(JSON.stringify({ type: 'presence', peer_id: p.peer_id, data: p.presence,
          presence_source: p.presence_source, sim_corroborated: p.sim_corroborated === true }))
        for (const [cam, data] of Object.entries(p.cameras ?? {})) {
          this.deliver(JSON.stringify({ type: 'camera_meta', peer_id: p.peer_id, cam, data }))
        }
        if (p.health) this.deliver(JSON.stringify({ type: 'health', peer_id: p.peer_id, data: p.health }))
      }
    })
  }

  private camera(peer: string, cam: string): void {
    let n = 0
    const tick = () => { void cameraFrame(peer, cam, n++).then(b => this.deliver(b)) }
    tick()
    this.every(250, tick)
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    if (this.readyState !== 1 || typeof data !== 'string') return
    let msg: any
    try { msg = JSON.parse(data) } catch { return }
    if (msg?.type === 'ping') { this.deliver(JSON.stringify({ type: 'pong' })); return }
    if (msg?.type !== 'say') return
    const reply = 'This is a demo build, so no agent is connected. On a real dashboard I would plan this '
      + 'with the fleet tools and ask before moving any robot.'
    const words = reply.split(' ')
    words.forEach((w, i) => setTimeout(() => this.deliver(JSON.stringify({ type: 'text', text: (i ? ' ' : '') + w })), 60 * i))
    setTimeout(() => this.deliver(JSON.stringify({ type: 'done' })), 60 * words.length + 50)
  }

  close(code = 1000, reason = ''): void {
    if (this.readyState >= 2) return
    this.readyState = 3
    for (const t of this.timers) clearInterval(t)
    meshSockets.delete(this)
    setTimeout(() => this.fire('close', new CloseEvent('close', { code, reason, wasClean: true })), 0)
  }
}

/* ------------------------------ banner ----------------------------- */

function banner(): void {
  const el = document.createElement('div')
  el.setAttribute('role', 'note')
  el.textContent = 'Demo build: sample robots and canned data, no server or robot behind this page.'
  el.style.cssText = 'padding:4px 12px;font:12px/1.6 monospace;text-align:center;'
    + 'background:var(--amber,#946e00);color:var(--on-warn,#fff)'
  document.body.prepend(el)
}

export function installDemo(): void {
  const realFetch = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const href = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const url = new URL(href, location.href)
    // Regexes, not path strings: scripts/gen-bundle-routes.mjs reads quoted /api paths as routes.
    if (!/^\/(api\/|openapi\.json$)/.test(url.pathname)) return realFetch(input, init)
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
    return answer(method, url, init?.body)
  }
  window.WebSocket = DemoSocket as unknown as typeof WebSocket
  banner()
}
