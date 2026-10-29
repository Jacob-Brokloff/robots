#!/usr/bin/env node
/**
 * The per-PR preview site: the dashboard in demo mode (src/demo), as plain static files in dist/.
 *
 * Laid out the way the Python server serves the real thing, so no URL in the bundle changes:
 * the build lands in dist/static/ (vite.config.ts `base: '/static/'`), the page is copied up to
 * dist/index.html (the server answers `/` with static/index.html), and the hand-written sim twin
 * files the Vite build does not own (twin.js, three.js) are copied in from ../static/.
 *
 * Never writes to ../static/: that directory is the shipped bundle and stays a normal build.
 */
import fs from 'node:fs'
import path from 'node:path'
import { build } from 'vite'

const OUT = path.resolve('dist')
const STATIC = path.join(OUT, 'static')
const SHIPPED = path.resolve('../static')

process.env.VITE_DEMO = '1'
fs.rmSync(OUT, { recursive: true, force: true })
await build({ build: { outDir: STATIC, emptyOutDir: true } })

fs.copyFileSync(path.join(STATIC, 'index.html'), path.join(OUT, 'index.html'))
for (const f of ['twin.js', 'vendor/three.module.min.js', 'vendor/OrbitControls.js']) {
  fs.copyFileSync(path.join(SHIPPED, f), path.join(STATIC, f))
}
console.log(`  preview site in ${path.relative(process.cwd(), OUT)}/ (demo mode, no backend)`)
