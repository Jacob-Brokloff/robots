/**
 * GET /feedback-api/shot/<uuid>.jpg: a screenshot the feedback widget stored (see ../issue.ts),
 * for the image in its GitHub issue. Only JPEGs under shots/ are served, by exact id.
 */
import type { Env } from '../issue'

interface Ctx { env: Env; params: { id?: string | string[] } }

export async function onRequestGet({ env, params }: Ctx): Promise<Response> {
  const id = typeof params.id === 'string' ? params.id : ''
  if (!/^[0-9a-f-]{36}\.jpg$/.test(id) || !env.FEEDBACK_SHOTS) return new Response('Not found', { status: 404 })
  const obj = await env.FEEDBACK_SHOTS.get(`shots/${id}`)
  if (!obj) return new Response('Not found', { status: 404 })
  return new Response(obj.body, {
    headers: {
      'Content-Type': 'image/jpeg',
      'Cache-Control': 'public, max-age=31536000, immutable',
      'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'none'",
    },
  })
}
