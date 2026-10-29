import { useEffect, useRef } from 'react'
import type { Peer } from '../types'
import CameraTile from './CameraTile'

/**
 * One camera, as large as the window allows, with the robot's other cameras one tap away.
 * The card's tiles are thumbnails: three 4:3 feeds in a card's width are too small to judge a grasp by.
 */
export default function CameraFocus({ peer, cam, onCam, onClose }: {
  peer: Peer; cam: string; onCam: (cam: string) => void; onClose: () => void
}) {
  const cams = Object.keys(peer.cameras ?? {})
  const boxRef = useRef<HTMLDivElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => { closeRef.current?.focus() }, [])

  // Capture phase, so Escape closes this view and not also the screen under it. Only Escape and the
  // arrows are taken: "." must still reach the stop sheet, which opens above this view.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Leaving fullscreen is the browser's own Escape; this one closes the view.
        if (document.fullscreenElement) return
        e.stopPropagation()
        onClose()
      } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && cams.length > 1) {
        const i = cams.indexOf(cam)
        const step = e.key === 'ArrowRight' ? 1 : -1
        onCam(cams[(i + step + cams.length) % cams.length])
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [cam, cams.join('|'), onCam, onClose])  // eslint-disable-line react-hooks/exhaustive-deps

  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void boxRef.current?.requestFullscreen?.()
  }

  return (
    <div className="camfocus-backdrop" onClick={onClose}>
      <div ref={boxRef} className="camfocus" role="dialog" aria-modal="true"
           aria-label={`${peer.peer_id} ${cam} camera`} onClick={e => e.stopPropagation()}>
        <div className="camfocus-head">
          <b>{peer.peer_id}</b>
          <div className="camswitch">
            {cams.length > 1 && cams.map(c => (
              <button key={c} className={c === cam ? 'chip on' : 'chip'}
                      aria-pressed={c === cam} onClick={() => onCam(c)}>{c}</button>
            ))}
          </div>
          {document.fullscreenEnabled && (
            <button className="btn ghost" onClick={fullscreen} aria-label="toggle fullscreen" title="fullscreen">⛶</button>
          )}
          <button ref={closeRef} className="btn ghost" onClick={onClose} aria-label="close camera view">✕</button>
        </div>
        <CameraTile key={cam} peerId={peer.peer_id} cam={cam} meta={peer.cameras?.[cam]} big />
      </div>
    </div>
  )
}
