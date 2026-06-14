import type { MarketType, Portfolio, StrategyKey } from '../../types'

export type DecisionSource = StrategyKey | 'subjective'
export type PersonalBetStatus = 'pending' | 'settled' | 'void'

export interface PersonalBet {
  id: string
  createdAt: string
  targetDate: string
  matchId?: string
  matchLabel: string
  market: MarketType | '自定义'
  selection: string
  odds: number
  stake: number
  decisionSource: DecisionSource
  status: PersonalBetStatus
  payout?: number
  settledAt?: string
  note?: string
  forecastGeneratedAt?: string
  modelProbability?: number
}

export interface ModelDaySnapshot {
  targetDate: string
  generatedAt: string
  coverage: number
  portfolios: Portfolio[]
}

export interface PersonalBetLedger {
  schemaVersion: 1
  initialBankroll: number
  bets: PersonalBet[]
  modelSnapshots: ModelDaySnapshot[]
}

export interface StrategyHistoryDay {
  targetDate: string
  generatedAt: string
  coverage: number
  strategies: Array<{
    key: StrategyKey
    name: string
    stake: number
    payout: number | null
    profit: number | null
    roi: number | null
    status: 'pending' | 'settled' | 'no-bet'
  }>
}

export interface StrategyHistory {
  generatedAt: string
  finalDate: string
  days: StrategyHistoryDay[]
}

export interface ProjectionSummary {
  key: StrategyKey | 'mixed'
  name: string
  color: string
  medianPath: number[]
  p05: number
  median: number
  p95: number
  stopProbability: number
  medianMaxDrawdown: number
}
