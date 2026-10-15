// Browser smoke test. Start the backend (serving frontend/dist) on :8000, then: node e2e/smoke.mjs
// Requires: npm i -D playwright (uses an installed Chromium).
import { chromium } from 'playwright'
const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
const go = (l) => page.getByRole('button', { name: l }).first().click()
await page.goto('http://127.0.0.1:8000/'); await page.waitForTimeout(1200)
// faulty sample -> validation gate
await page.getByText('Warehouse AMR with design errors').locator('..').locator('..').getByRole('button', { name: 'Open sample' }).click()
await page.waitForTimeout(2000)
await go('Circuit studio'); await page.waitForTimeout(2500)
await page.screenshot({ path: '/tmp/rv-20_faulty_circuit.png' })
await go('Simulation & nav lab'); await page.waitForTimeout(800)
await page.getByRole('button', { name: 'Run simulation' }).click(); await page.waitForTimeout(1500)
await page.screenshot({ path: '/tmp/rv-21_blocked.png' })
const blocked = await page.getByText('blocking issue').count()
console.log('validation gate shown:', blocked === 1)
// good sample
await go('Dashboard'); await page.waitForTimeout(800)
await page.getByText('Warehouse AMR (complete digital twin)').locator('..').locator('..').getByRole('button', { name: 'Open sample' }).click()
await page.waitForTimeout(2000)
// world: add box, check hierarchy count, undo
const count = async () => (await page.getByText(/Scene hierarchy \((\d+)\)/).textContent())
const c0 = await count()
await page.getByRole('button', { name: 'Box obstacle' }).click(); await page.waitForTimeout(500)
const c1 = await count()
await page.keyboard.press('Control+z'); await page.waitForTimeout(500)
const c2 = await count()
console.log('add/undo:', c0, '->', c1, '->', c2)
// circuit: wire LED
await go('Circuit studio'); await page.waitForTimeout(2500)
await page.screenshot({ path: '/tmp/rv-22_circuit_fit.png' })
await go('Simulation & nav lab'); await page.waitForTimeout(800)
await page.locator('select').filter({ hasText: 'real time' }).selectOption('0')
await page.getByRole('button', { name: 'Run simulation' }).click()
for (let i = 0; i < 60; i++) { await page.waitForTimeout(1000); if (await page.getByText('Navigation performance').count()) break }
await page.screenshot({ path: '/tmp/rv-23_sim_done.png' })
const done = await page.getByText('Navigation performance').count()
const real = errors.filter((e) => !e.includes('409'))  // the 409 is the expected validation gate
console.log('simulation finished:', done === 1, 'page errors:', real)
await browser.close()
if (blocked !== 1 || c0 !== c2 || c0 === c1 || done !== 1 || real.length) process.exit(1)
