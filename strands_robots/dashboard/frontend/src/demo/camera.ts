/**
 * Demo camera frames: JPEGs drawn in the browser, so a preview build ships no video and no
 * pictures of anyone's lab. Each frame names its robot and camera, and a block swings across it,
 * so a reviewer can see the tile is live and which feed it is.
 *
 * A short loop is encoded once per feed and then replayed: JPEG encoding is the expensive part
 * (measured at most of a page's main thread with five feeds encoding every frame).
 */

// Half the advertised 640x480: a tile shows it the same, and encoding stays cheap with five feeds open.
/** Frames in one loop of the swing. */
const LOOP = 16
const W = 320
const H = 240

let canvas: OffscreenCanvas | HTMLCanvasElement | null = null

function surface(): OffscreenCanvas | HTMLCanvasElement {
  if (canvas) return canvas
  if (typeof OffscreenCanvas !== 'undefined') canvas = new OffscreenCanvas(W, H)
  else {
    const c = document.createElement('canvas')
    c.width = W
    c.height = H
    canvas = c
  }
  return canvas
}

/** A stable hue per feed, so three tiles side by side do not look like one picture. */
function hueOf(key: string): number {
  let h = 0
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

function drawFrame(peer: string, cam: string, step: number): Promise<Blob> {
  const c = surface()
  // willReadFrequently keeps the canvas in CPU memory: a GPU canvas makes every encode wait on a
  // readback, which on a busy page measured ~150 ms a frame instead of ~1 ms.
  const ctx = c.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D
  const t = (step / LOOP) * 2 * Math.PI
  const hue = hueOf(`${peer}/${cam}`)

  const sky = ctx.createLinearGradient(0, 0, 0, H)
  sky.addColorStop(0, `hsl(${hue} 30% 18%)`)
  sky.addColorStop(1, `hsl(${hue} 25% 8%)`)
  ctx.fillStyle = sky
  ctx.fillRect(0, 0, W, H)

  // A floor grid in perspective, drifting slowly as if the head camera pans.
  ctx.strokeStyle = `hsl(${hue} 40% 35% / .55)`
  ctx.lineWidth = 1
  const horizon = H * 0.45
  const drift = (step / LOOP) * 40
  for (let i = 0; i < 12; i++) {
    const y = horizon + ((i * 20 + drift / 2) ** 1.35) / 4
    if (y > H) break
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke()
  }
  for (let x = -W; x <= 2 * W; x += 40) {
    ctx.beginPath(); ctx.moveTo(W / 2, horizon); ctx.lineTo(x + Math.sin(t) * 15, H); ctx.stroke()
  }

  // Something to watch: a gripper-sized block swinging across the frame.
  const bx = W / 2 + Math.sin(t) * W * 0.25
  const by = H * 0.62 + Math.cos(2 * t) * 9
  ctx.fillStyle = `hsl(${(hue + 150) % 360} 70% 55%)`
  ctx.fillRect(bx - 14, by - 14, 28, 28)

  ctx.fillStyle = 'rgba(0, 0, 0, .55)'
  ctx.fillRect(0, 0, W, 20)
  ctx.fillStyle = '#ffffff'
  ctx.font = '10px monospace'
  ctx.fillText(`${peer} / ${cam}`, 6, 14)
  ctx.fillStyle = 'rgba(255, 255, 255, .7)'
  ctx.fillText('DEMO FEED, NO CAMERA', 6, H - 8)

  if ('convertToBlob' in c) return c.convertToBlob({ type: 'image/jpeg', quality: 0.7 })
  return new Promise((resolve, reject) =>
    (c as HTMLCanvasElement).toBlob(b => (b ? resolve(b) : reject(new Error('no frame'))), 'image/jpeg', 0.7))
}

const loops = new Map<string, Promise<Blob[]>>()

/** The feed's next frame, from its loop (encoded on first use). */
export async function cameraFrame(peer: string, cam: string, n: number): Promise<Blob> {
  const key = `${peer}/${cam}`
  let loop = loops.get(key)
  if (!loop) {
    loop = (async () => {
      const out: Blob[] = []
      for (let i = 0; i < LOOP; i++) out.push(await drawFrame(peer, cam, i))
      return out
    })()
    loops.set(key, loop)
  }
  return (await loop)[n % LOOP]
}
