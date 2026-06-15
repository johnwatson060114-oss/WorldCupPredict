import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const outputPath = path.join(projectRoot, '.cache', 'pipeline', 'sporttery-live.json')

const edgeCandidates = [
  process.env.EDGE_PATH,
  path.join(process.env['PROGRAMFILES(X86)'] ?? '', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
  path.join(process.env.PROGRAMFILES ?? '', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
].filter(Boolean)

async function existingEdgePath() {
  for (const candidate of edgeCandidates) {
    try {
      await fs.access(candidate)
      return candidate
    } catch {
      // Try the next standard Edge installation path.
    }
  }
  throw new Error('Microsoft Edge executable was not found')
}

async function capture(page, pageUrl, poolCode) {
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes('getMatchCalculatorV1.qry')
      && new URL(response.url()).searchParams.get('poolCode')?.split(',').includes(poolCode),
    { timeout: 45_000 },
  )
  await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 45_000 })
  const response = await responsePromise
  if (!response.ok()) throw new Error(`Sporttery ${poolCode} endpoint returned ${response.status()}`)
  const payload = await response.json()
  if (!payload.success || payload.errorCode !== '0') {
    throw new Error(`Sporttery ${poolCode} response was not successful`)
  }
  return { endpoint: response.url(), payload }
}

async function captureMixed(page) {
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes('getMatchCalculatorV1.qry')
      && !new URL(response.url()).searchParams.has('poolCode'),
    { timeout: 45_000 },
  )
  await page.goto('https://m.sporttery.cn/mjc/jsq/zqhhgg/', { waitUntil: 'domcontentloaded', timeout: 45_000 })
  const response = await responsePromise
  if (!response.ok()) throw new Error(`Sporttery mixed endpoint returned ${response.status()}`)
  const payload = await response.json()
  if (!payload.success || payload.errorCode !== '0') {
    throw new Error('Sporttery mixed response was not successful')
  }
  return { endpoint: response.url(), payload }
}

const browser = await chromium.launch({
  headless: true,
  executablePath: await existingEdgePath(),
})

try {
  const context = await browser.newContext({ locale: 'zh-CN' })
  const page = await context.newPage()
  const spf = await capture(page, 'https://m.sporttery.cn/mjc/jsq/zqspf/', 'had')
  const score = await capture(page, 'https://m.sporttery.cn/mjc/jsq/zqbf/', 'crs')
  const mixed = await captureMixed(page)
  await fs.mkdir(path.dirname(outputPath), { recursive: true })
  await fs.writeFile(outputPath, JSON.stringify({
    schemaVersion: 1,
    fetchedAt: new Date().toISOString(),
    spf,
    score,
    mixed,
  }, null, 2), 'utf8')
  console.log(`Wrote ${outputPath}`)
} finally {
  await browser.close()
}
