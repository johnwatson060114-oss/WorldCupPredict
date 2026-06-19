import type { MarketType, Portfolio, StrategyKey } from '../../types'
import type { PassType } from './pass-types'

export type DecisionSource = StrategyKey | 'subjective'
export type PersonalBetStatus = 'pending' | 'settled' | 'void'

export interface PersonalBetLeg {
  matchId: string
  matchLabel: string
  lotteryCode?: string
  kickoffBeijing?: string
  matchDate?: string
  market: MarketType
  selection: string
  odds: number
  settlementOdds?: number
  modelProbability?: number
}

export interface PersonalBet {
  id: string
  createdAt: string
  purchaseDate?: string
  targetDate: string
  matchId?: string
  matchLabel: string
  market: MarketType | '混合过关' | '自定义'
  selection: string
  odds: number
  stake: number
  standardStake?: number
  passType?: PassType
  multiple?: number
  ticketCount?: number
  theoreticalPayout?: number
  decisionSource: DecisionSource
  status: PersonalBetStatus
  payout?: number
  settledAt?: string
  oddsVerifiedAt?: string
  oddsSource?: string
  note?: string
  forecastGeneratedAt?: string
  modelProbability?: number
  legs?: PersonalBetLeg[]
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
  review?: {
    snapshotLabel: string
    summary: {
      matchCount: number
      outcomeAccuracy: number
      exactScoreAccuracy: number
      meanGoalAbsoluteError: number
      logLoss: number
      brier: number
      strategyDiagnosis: string
    }
    matches: Array<{
      matchId: string
      label: string
      predictedScore: string
      actualScore: string
      outcomeCorrect: boolean
      exactScore: boolean
      goalAbsoluteError: number
      actualOutcomeProbability: number
      logLoss: number
      brier: number
      diagnosis: string
    }>
  } | null
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

export interface ActualStrategySummary {
  key: StrategyKey
  name: string
  color: string
  balance: number
  profit: number
  totalStake: number
  roi: number | null
  settledDays: number
  path: number[]
}
