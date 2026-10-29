/**
 * The demo fleet: the XLeRobot setup this fork drives, as the mesh would publish it.
 *
 * - `woodside` is the real 2-wheel XLeRobot on the Pi (three cameras, 14 arm/head joints + base)
 * - `leader-arms` is the pair of SO-101 leaders, read-only, publishing the `leader` teleop stream
 * - `xlerobot-sim-*` is the sim twin, copied from a real dashboard's snapshot (captured.json)
 *
 * Nothing here is measured: joints follow slow sine waves, and woodside mirrors the leaders while
 * demo teleop is on, so the cards move the way a live fleet does.
 */
import captured from './captured.json'
import type { ActivityEntry, MeshInfo, Peer } from '../types'

const ARM = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper']
const ARM_JOINTS = ['left', 'right'].flatMap(side => ARM.map(j => `${side}_arm_${j}`))
const XLE_KEYS = [...ARM_JOINTS, 'head_motor_1', 'head_motor_2'].map(j => `${j}.pos`)
const BASE_KEYS = ['x.vel', 'theta.vel']
const WOODSIDE_CAMS = ['head', 'left_wrist', 'right_wrist']

export const DASHBOARD_ID = 'dashboard-desktop'
export const LEADER = 'leader-arms'
export const ROBOT = 'woodside'

const nowS = () => Date.now() / 1000
const started = nowS()

/** Degrees (gripper 0-100), the units a lerobot SO-101 bus reports. */
function armPose(t: number, phase: number): Record<string, number> {
  const out: Record<string, number> = {}
  ARM_JOINTS.forEach((j, i) => {
    const wave = Math.sin(t * 0.6 + phase + i * 0.7)
    out[`${j}.pos`] = j.endsWith('gripper') ? 30 + 25 * wave : 18 * wave
  })
  out['head_motor_1.pos'] = 8 * Math.sin(t * 0.3 + phase)
  out['head_motor_2.pos'] = -5 + 4 * Math.sin(t * 0.25 + phase)
  return out
}

const lockout = { state: 'unknown', reason: 'no e-stop or resume seen since this dashboard started' }

/** Whether woodside is following the leaders (demo teleop). */
export const teleop = { following: true }

/** A task started from the run form: shown on the card until it "finishes". */
export const tasks: Record<string, { instruction: string; until: number }> = {}

/** Set by the e-stop routes; every card reads it. */
export const safety = { locked: false, since: 0 }

function peerLockout() {
  return safety.locked
    ? { state: 'locked', reason: 'an e-stop from this dashboard (demo)', since: safety.since, by: 'demo' }
    : lockout
}

function taskFields(id: string) {
  const task = tasks[id]
  if (!task) return { task_status: 'idle' }
  if (task.until < nowS()) { delete tasks[id]; return { task_status: 'completed' } }
  return { task_status: 'running', instruction: task.instruction }
}

function woodside(t: number): Peer {
  const lead = armPose(t - 0.15, 0)
  const own = armPose(t, 2.1)
  const joints: Record<string, number> = teleop.following && !safety.locked ? lead : own
  joints['x.vel'] = 0
  joints['theta.vel'] = 0
  return {
    peer_id: ROBOT, last_seen: t, stale: false, origin: 'external', reach: 'lan', presence_source: 'wire',
    lockout: peerLockout(),
    presence: {
      robot_id: ROBOT, robot_type: 'robot', hostname: 'woodside', tool_name: ROBOT, connected: true,
      hw: 'xlerobot_2wheels_client', cameras: WOODSIDE_CAMS, action_keys: [...XLE_KEYS, ...BASE_KEYS],
      topics: ['health'], timestamp: t, ...taskFields(ROBOT),
    },
    state: { peer_id: ROBOT, t, joints },
    health: { peer_id: ROBOT, t, cpu_load: 1.1 + 0.3 * Math.sin(t / 7), mem_pct: 41, disk_free_gb: 18.4,
      uptime_s: Math.round(t - started) + 86_400, temps: { cpu: 52 + 2 * Math.sin(t / 11) } },
    cameras: Object.fromEntries(WOODSIDE_CAMS.map(c => [c, { t, shape: [480, 640, 3], via: 'inline', latency_ms: 38 }])),
  }
}

function leaders(t: number): Peer {
  return {
    peer_id: LEADER, last_seen: t, stale: false, origin: 'external', reach: 'lan', presence_source: 'wire',
    lockout: peerLockout(),
    presence: {
      robot_id: LEADER, robot_type: 'robot', hostname: 'arch-desktop', tool_name: 'leader_arms', connected: true,
      hw: 'bi_so_leader', topics: [], timestamp: t, task_status: 'idle',
    },
    state: { peer_id: LEADER, t, joints: armPose(t - 0.15, 0) },
  }
}

/** The sim twin pair exactly as captured, re-stamped to now, with its arm joints swinging gently. */
function sims(t: number): Peer[] {
  return Object.values(captured.sim_peers as unknown as Record<string, Peer>).map(peer => {
    const p: Peer = structuredClone(peer)
    p.last_seen = t
    p.stale = false
    p.lockout = peerLockout()
    if (p.presence) p.presence = { ...p.presence, timestamp: t, ...taskFields(p.peer_id) }
    if (p.state) {
      p.state.t = t
      const joints = p.state.joints as Record<string, { position?: number; velocity?: number }> | undefined
      if (joints) {
        let i = 0
        for (const [name, j] of Object.entries(joints)) {
          if (/_(L|R)$/.test(name)) j.position = 0.35 * Math.sin(t * 0.6 + i++ * 0.7)
        }
      }
    }
    if (p.health) p.health = { ...p.health, t }
    if (p.cameras) for (const c of Object.values(p.cameras)) c.t = t
    return p
  })
}

export function fleet(t = nowS()): Record<string, Peer> {
  const peers = [woodside(t), leaders(t), ...sims(t)]
  return Object.fromEntries(peers.map(p => [p.peer_id, p]))
}

export function meshInfo(): MeshInfo {
  return { ...(captured.mesh as MeshInfo), peer_id: DASHBOARD_ID }
}

export function snapshot() {
  return {
    type: 'snapshot', dashboard_peer_id: DASHBOARD_ID, peers: fleet(), mesh: meshInfo(),
    absent_children: [], managed_no_presence: [], t: nowS(),
  }
}

/** The activity log, newest first, as /api/activity and the mesh socket report it. */
export const activity: ActivityEntry[] = [
  { t: started - 40, source: 'api', action: 'teleop_receive', target: ROBOT, ok: true, detail: `following ${LEADER}` },
  { t: started - 95, source: 'api', action: 'spawn', target: 'xlerobot-sim-2711', ok: true, detail: 'xlerobot mode=sim' },
  { t: started - 300, source: 'mesh', action: 'joined', target: LEADER, ok: true },
  { t: started - 320, source: 'mesh', action: 'joined', target: ROBOT, ok: true },
]

export const activityListeners: Array<(row: ActivityEntry) => void> = []

export function logActivity(entry: Omit<ActivityEntry, 't'>): ActivityEntry {
  const row = { t: nowS(), ...entry }
  activity.unshift(row)
  for (const fn of activityListeners) fn(row)
  return row
}
