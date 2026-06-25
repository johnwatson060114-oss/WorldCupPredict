import type { Portfolio, StrategyKey } from '../../types'
import type { ActualStrategySummary, PersonalBetLedger, ProjectionSummary, StrategyHistory } from './types'

export type ComparisonMode = 'matched' | 'all'

export interface ComparisonPoint {
  date: string
  userRoi: number | null
  modelRoi: number | null
}

export interface FairComparison {
  userRoi: number | null
  modelRoi: number | null
  userDays: number
  modelDays: number
  matchedDays: number
  userHitRate: number | null
  modelHitRate: number | null
  points: ComparisonPoint[]
}

const strategyColors: Record<StrategyKey | 'mixed', string> = {
  conservative: '#48d17b',
  balanced: '#429cff',
  aggressive: '#f06464',
  mixed: '#f5b942',
}

const strategyNames: Record<StrategyKey | 'mixed', string> = {
  conservative: '稳健',
  balanced: '均衡',
  aggressive: '激进',
  mixed: '我的混合策略',
}

export const actualStrategyPerformance = (history: StrategyHistory | null): { dates: string[]; summaries: ActualStrategySummary[]; pendingDays: number } => {
  const settledDates = (history?.days ?? [])
    .filter((day) => day.strategies.some((strategy) => strategy.status === 'settled'))
    .map((day) => day.targetDate)
  const pendingDays = (history?.days ?? []).filter((day) => day.strategies.some((strategy) => strategy.status === 'pending')).length
  const summaries = (['conservative', 'balanced', 'aggressive'] as StrategyKey[]).map((key) => {
    let balance = 200
    let totalStake = 0
    let settledDays = 0
    const path = [balance]
    for (const date of settledDates) {
      const day = history?.days.find((item) => item.targetDate === date)
      const strategy = day?.strategies.find((item) => item.key === key)
      if (balance >= 2 && strategy?.status === 'settled' && strategy.profit !== null) {
        const scale = balance / 200
        totalStake += strategy.stake * scale
        balance = Math.max(0, balance + strategy.profit * scale)
        settledDays += 1
      }
      path.push(round(balance))
    }
    const profit = balance - 200
    return {
      key,
      name: strategyNames[key],
      color: strategyColors[key],
      balance: round(balance),
      profit: round(profit),
      totalStake: round(totalStake),
      roi: totalStake > 0 ? profit / totalStake : null,
      settledDays,
      path,
    }
  })
  return { dates: ['起始', ...settledDates], summaries, pendingDays }
}

const round = (value: number) => Math.round(value * 100) / 100

const userDays = (ledger: PersonalBetLedger) => {
  const map = new Map<string, { stake: number; profit: number; wins: number; bets: number }>()
  for (const bet of ledger.bets) {
    if (bet.status !== 'settled') continue
    const current = map.get(bet.targetDate) ?? { stake: 0, profit: 0, wins: 0, bets: 0 }
    current.stake += bet.stake
    current.profit += (bet.payout ?? 0) - bet.stake
    current.wins += (bet.payout ?? 0) > 0 ? 1 : 0
    current.bets += 1
    map.set(bet.targetDate, current)
  }
  return map
}

const modelDays = (history: StrategyHistory | null, key: StrategyKey = 'balanced') => {
  const map = new Map<string, { stake: number; profit: number; wins: number; bets: number }>()
  for (const day of history?.days ?? []) {
    const strategy = day.strategies.find((item) => item.key === key)
    if (!strategy || strategy.status !== 'settled' || strategy.profit === null) continue
    map.set(day.targetDate, {
      stake: strategy.stake,
      profit: strategy.profit,
      wins: strategy.profit > 0 ? 1 : 0,
      bets: 1,
    })
  }
  return map
}

const aggregate = (days: Map<string, { stake: number; profit: number; wins: number; bets: number }>, dates: string[]) => {
  let stake = 0
  let profit = 0
  let wins = 0
  let bets = 0
  for (const date of dates) {
    const day = days.get(date)
    if (!day) continue
    stake += day.stake
    profit += day.profit
    wins += day.wins
    bets += day.bets
  }
  return {
    roi: stake > 0 ? profit / stake : null,
    hitRate: bets > 0 ? wins / bets : null,
  }
}

export const buildFairComparison = (ledger: PersonalBetLedger, history: StrategyHistory | null, mode: ComparisonMode): FairComparison => {
  const users = userDays(ledger)
  const models = modelDays(history)
  const matchedDates = [...users.keys()].filter((date) => models.has(date)).sort()
  const userDates = mode === 'matched' ? matchedDates : [...users.keys()].sort()
  const modelDates = mode === 'matched' ? matchedDates : [...models.keys()].sort()
  const userAggregate = aggregate(users, userDates)
  const modelAggregate = aggregate(models, modelDates)
  const chartDates = mode === 'matched'
    ? matchedDates
    : [...new Set([...userDates, ...modelDates])].sort()
  let userStake = 0
  let userProfit = 0
  let modelStake = 0
  let modelProfit = 0
  const points = chartDates.map((date) => {
    const user = users.get(date)
    const model = models.get(date)
    if (user) { userStake += user.stake; userProfit += user.profit }
    if (model) { modelStake += model.stake; modelProfit += model.profit }
    return {
      date,
      userRoi: userStake > 0 ? userProfit / userStake : null,
      modelRoi: modelStake > 0 ? modelProfit / modelStake : null,
    }
  })
  return {
    userRoi: userAggregate.roi,
    modelRoi: modelAggregate.roi,
    userDays: userDates.length,
    modelDays: modelDates.length,
    matchedDays: matchedDates.length,
    userHitRate: userAggregate.hitRate,
    modelHitRate: modelAggregate.hitRate,
    points,
  }
}

const matchDates = (() => {
  const dates: string[] = []
  const addRange = (start: string, end: string) => {
    const cursor = new Date(`${start}T00:00:00Z`)
    const finish = new Date(`${end}T00:00:00Z`)
    while (cursor <= finish) {
      dates.push(cursor.toISOString().slice(0, 10))
      cursor.setUTCDate(cursor.getUTCDate() + 1)
    }
  }
  addRange('2026-06-11', '2026-07-07')
  addRange('2026-07-09', '2026-07-11')
  addRange('2026-07-14', '2026-07-15')
  addRange('2026-07-18', '2026-07-19')
  return dates
})()

const rng = (seed: number) => () => {
  seed |= 0
  seed = seed + 0x6D2B79F5 | 0
  let value = Math.imul(seed ^ seed >>> 15, 1 | seed)
  value = value + Math.imul(value ^ value >>> 7, 61 | value) ^ value
  return ((value ^ value >>> 14) >>> 0) / 4294967296
}

const weightedSample = (portfolio: Portfolio, random: () => number) => {
  const total = portfolio.distribution.reduce((sum, point) => sum + point.probability, 0)
  if (total <= 0) return portfolio.median
  let needle = random() * total
  for (const point of portfolio.distribution) {
    needle -= point.probability
    if (needle <= 0) return point.bankroll
  }
  return portfolio.distribution.at(-1)?.bankroll ?? portfolio.median
}

const quantile = (values: number[], value: number) => {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * value))] ?? 0
}

const settledFactors = (history: StrategyHistory | null, key: StrategyKey) =>
  (history?.days ?? [])
    .map((day) => day.strategies.find((item) => item.key === key))
    .filter((item) => item?.status === 'settled' && item.profit !== null)
    .map((item) => 1 + (item!.profit! / 200))

const mixedWeights = (ledger: PersonalBetLedger) => {
  const weights: Record<StrategyKey, number> = { conservative: 0, balanced: 0, aggressive: 0 }
  for (const bet of ledger.bets) {
    const key = bet.decisionSource === 'subjective' ? 'balanced' : bet.decisionSource
    weights[key] += bet.stake
  }
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0)
  if (!total) return { conservative: 0, balanced: 1, aggressive: 0 }
  return {
    conservative: weights.conservative / total,
    balanced: weights.balanced / total,
    aggressive: weights.aggressive / total,
  }
}

const pickMixedPortfolio = (portfolios: Portfolio[], weights: ReturnType<typeof mixedWeights>, random: () => number) => {
  const needle = random()
  const key: StrategyKey = needle < weights.conservative
    ? 'conservative'
    : needle < weights.conservative + weights.balanced ? 'balanced' : 'aggressive'
  return portfolios.find((portfolio) => portfolio.key === key) ?? portfolios[0]
}

const pickMixedKey = (weights: ReturnType<typeof mixedWeights>, random: () => number): StrategyKey => {
  const needle = random()
  return needle < weights.conservative
    ? 'conservative'
    : needle < weights.conservative + weights.balanced ? 'balanced' : 'aggressive'
}

export const projectToFinal = (
  portfolios: Portfolio[],
  history: StrategyHistory | null,
  ledger: PersonalBetLedger,
  targetDate: string,
  samples = 2500,
): { dates: string[]; summaries: ProjectionSummary[] } => {
  const futureDates = matchDates.filter((date) => date >= targetDate)
  const dates = ['已结算', ...futureDates]
  const keys: Array<StrategyKey | 'mixed'> = ['conservative', 'balanced', 'aggressive', 'mixed']
  const weights = mixedWeights(ledger)
  const empiricalFactors: Record<StrategyKey, number[]> = {
    conservative: settledFactors(history, 'conservative'),
    balanced: settledFactors(history, 'balanced'),
    aggressive: settledFactors(history, 'aggressive'),
  }
  const summaries = keys.map((key, keyIndex) => {
    const paths: number[][] = []
    const finals: number[] = []
    const drawdowns: number[] = []
    let stopped = 0
    for (let sample = 0; sample < samples; sample += 1) {
      const random = rng(20260614 + keyIndex * 100_000 + sample)
      let balance = ledger.initialBankroll
      let peak = balance
      let maxDrawdown = 0
      if (key === 'mixed') {
        const settled = ledger.bets.filter((bet) => bet.status === 'settled').sort((a, b) => a.targetDate.localeCompare(b.targetDate))
        for (const bet of settled) balance = Math.max(0, balance + (bet.payout ?? 0) - bet.stake)
      } else {
        for (const factor of settledFactors(history, key)) balance = Math.max(0, balance * factor)
      }
      const path = [round(balance)]
      peak = Math.max(peak, balance)
      for (const _date of futureDates) {
        if (balance < 2) {
          path.push(round(balance))
          continue
        }
        const empiricalKey = key === 'mixed' ? pickMixedKey(weights, random) : key
        const factors = empiricalFactors[empiricalKey]
        if (factors.length >= 5) {
          balance = Math.max(0, balance * factors[Math.floor(random() * factors.length)])
        } else {
          const portfolio = key === 'mixed'
            ? pickMixedPortfolio(portfolios, weights, random)
            : portfolios.find((item) => item.key === key) ?? portfolios[0]
          const sampledBankroll = weightedSample(portfolio, random)
          balance = Math.max(0, balance * sampledBankroll / 200)
        }
        peak = Math.max(peak, balance)
        maxDrawdown = Math.max(maxDrawdown, peak > 0 ? (peak - balance) / peak : 0)
        path.push(round(balance))
      }
      if (balance < 2) stopped += 1
      paths.push(path)
      finals.push(balance)
      drawdowns.push(maxDrawdown)
    }
    const medianPath = dates.map((_, index) => quantile(paths.map((path) => path[index] ?? 0), 0.5))
    return {
      key,
      name: strategyNames[key],
      color: strategyColors[key],
      medianPath: medianPath.map(round),
      p05: round(quantile(finals, 0.05)),
      median: round(quantile(finals, 0.5)),
      p95: round(quantile(finals, 0.95)),
      stopProbability: stopped / samples,
      medianMaxDrawdown: quantile(drawdowns, 0.5),
    }
  })
  return { dates, summaries }
}

export const personalSummary = (ledger: PersonalBetLedger) => {
  const active = ledger.bets.filter((bet) => bet.status !== 'void')
  const settled = active.filter((bet) => bet.status === 'settled')
  const totalStaked = (ledger.baselineStake ?? 0) + active.reduce((sum, bet) => sum + bet.stake, 0)
  const realizedProfit = (ledger.baselineProfit ?? 0) + settled.reduce((sum, bet) => sum + (bet.payout ?? 0) - bet.stake, 0)
  const pendingExposure = active.filter((bet) => bet.status === 'pending').reduce((sum, bet) => sum + bet.stake, 0)
  return { totalStaked, realizedProfit, pendingExposure, settledCount: settled.length }
}
