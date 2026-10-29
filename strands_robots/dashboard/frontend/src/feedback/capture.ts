import { domToCanvas } from 'modern-screenshot'

export interface Box { x: number; y: number; w: number; h: number }

/** The page's own colour behind the capture, so a transparent body does not come out black. */
function pageBackground(): string {
  const bg = getComputedStyle(document.body).backgroundColor
  return bg && bg !== 'rgba(0, 0, 0, 0)' ? bg : '#ffffff'
}

/**
 * A JPEG of what the reviewer sees right now (the viewport, not the whole page), with their box
 * drawn on it. The widget itself is left out. Known gap: on a page scrolled down, fixed bars (the agent
 * dock) render where they would sit on the unscrolled page, so they can fall outside the crop.
 * Capped near 2 MB so the upload stays small: a big screen at high density is retried at a lower scale.
 */
export async function captureViewport(widgetRoot: Element, box: Box | null): Promise<string> {
  const vw = window.innerWidth
  const vh = window.innerHeight
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
    const url = out.toDataURL('image/jpeg', 0.82)
    if (url.length < 2_000_000) return url
  }
  throw new Error('the screenshot is too large to send')
}
