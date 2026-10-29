import { domToCanvas } from 'modern-screenshot'

export interface Box { x: number; y: number; w: number; h: number }

/** The page's own colour behind the capture, so a transparent body does not come out black. */
function pageBackground(): string {
  const bg = getComputedStyle(document.body).backgroundColor
  return bg && bg !== 'rgba(0, 0, 0, 0)' ? bg : '#ffffff'
}

/**
 * JPEGs of what the reviewer sees right now (the viewport, not the whole page), with their box
 * drawn on it, plus a close-up of the box and some context around it, so a reader (or the label bot)
 * sees the spot without hunting for it in a full screen. The widget itself is left out. Known gap: on a
 * page scrolled down, fixed bars (the agent dock) render where they would sit on the unscrolled page,
 * so they can fall outside the crop. Capped near 2 MB in total so the upload stays small: a big screen
 * at high density is retried at a lower scale, and if the pair never fits the full shot goes alone.
 */
export async function captureViewport(widgetRoot: Element, box: Box | null): Promise<{ full: string; closeup: string }> {
  const vw = window.innerWidth
  const vh = window.innerHeight
  let alone: { full: string; closeup: string } | null = null
  for (const scale of [Math.min(window.devicePixelRatio || 1, 1.5), 1, 0.6]) {
    const page = await domToCanvas(document.body, {
      scale,
      backgroundColor: pageBackground(),
      filter: n => n !== widgetRoot,
      features: { restoreScrollPosition: true },
      timeout: 8000,
    })
    const out = document.createElement('canvas')
    out.width = Math.round(vw * scale)
    out.height = Math.round(vh * scale)
    const ctx = out.getContext('2d')!
    // The capture is the whole body; shift it so the part on screen lands at the canvas origin.
    const body = document.body.getBoundingClientRect()
    ctx.drawImage(page, body.left * scale, body.top * scale)
    if (box) {
      ctx.lineWidth = 3 * scale
      ctx.strokeStyle = '#ff2d55'
      ctx.fillStyle = 'rgba(255, 45, 85, .12)'
      ctx.fillRect(box.x * scale, box.y * scale, box.w * scale, box.h * scale)
      ctx.strokeRect(box.x * scale, box.y * scale, box.w * scale, box.h * scale)
    }
    const full = out.toDataURL('image/jpeg', 0.82)
    const closeup = box ? closeupOf(out, box, scale) : ''
    if (full.length + closeup.length < 2_000_000) return { full, closeup }
    if (!alone && full.length < 2_000_000) alone = { full, closeup: '' }
  }
  if (alone) return alone
  throw new Error('the screenshot is too large to send')
}

/** The box with room around it (at least 60 px, or half its size), cut from the marked viewport. */
function closeupOf(marked: HTMLCanvasElement, box: Box, scale: number): string {
  const padX = Math.max(60, box.w / 2)
  const padY = Math.max(60, box.h / 2)
  const x = Math.max(0, box.x - padX)
  const y = Math.max(0, box.y - padY)
  const w = Math.min(window.innerWidth, box.x + box.w + padX) - x
  const h = Math.min(window.innerHeight, box.y + box.h + padY) - y
  if (w <= 0 || h <= 0) return ''
  const crop = document.createElement('canvas')
  crop.width = Math.round(w * scale)
  crop.height = Math.round(h * scale)
  crop.getContext('2d')!.drawImage(marked, x * scale, y * scale, crop.width, crop.height, 0, 0, crop.width, crop.height)
  return crop.toDataURL('image/jpeg', 0.9)
}
