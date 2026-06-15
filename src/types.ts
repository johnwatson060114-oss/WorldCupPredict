export type Outcome = 'home' | 'draw' | 'away'
export type MarketType = '胜平负' | '让球胜平负' | '比分' | '总进球数' | '半全场'
export type Recommendation = '重点推荐' | '小注可选' | '观察' | '不建议' | '未开售'
export type StrategyKey = 'conservative' | 'balanced' | 'aggressive'

export interface ScoreProbability {
  score: string
  probability: number
  odds?: number
}

export interface FactorContribution {
  label: string
  direction: 'home' | 'away' | 'neutral'
  value: number
  note: string
  active: boolean
  admissionStatus?: 'core' | 'enabled' | 'observation_only'
  uncertaintyOnly?: boolean
  admissionReason?: string
}

export interface SimulationQuality {
  actualPaths: number
  monteCarloStandardError: { home: number; draw: number; away: number }
  confidence95: { home: [number, number]; draw: [number, number]; away: [number, number] }
  convergence: Array<{
    paths: number
    outcomes: { home: number; draw: number; away: number }
    maxDeltaFromPrevious: number | null
  }>
}

export interface LineupImpact {
  side: 'home' | 'away'
  starterId: string
  starter: string
  replacementId?: string
  replacement?: string
  position: string
  attackDelta?: number
  defenseDelta?: number
  status: 'applied' | 'missing_replacement_value'
  modelVersion: string
  sourceUrl: string
  observedAt?: string
}

export interface IntelligenceEvent {
  event_id: string
  event_type: string
  subject: { type: string; id: string; name: string }
  teams: string[]
  target_date: string
  source_url: string
  published_at: string
  confirmation: 'official' | 'reliable_report' | 'unverified'
  confidence: number
  claim: string
  conflicts: Array<{ source_url: string; claim: string }>
  conclusion: Record<string, unknown>
}

export interface SourceEvidence {
  source: string
  field: string
  observedAt: string
  confidence: number
  status: 'fresh' | 'stale' | 'manual' | 'missing'
}

export interface MarketQuote {
  id: string
  matchId: string
  market: MarketType
  selection: string
  handicap?: number
  odds: number | null
  modelProbability: number
  marketProbability: number | null
  coverage?: number
  rawExpectedReturn: number | null
  robustExpectedReturn: number | null
  singleEligible: boolean
  available: boolean
  recommendation: Recommendation
  reason: string
  observedAt: string
}

export interface MatchForecast {
  id: string
  apiFixtureId?: number | null
  lotteryCode: string
  kickoff: string
  kickoffBeijing: string
  venue: string
  homeTeam: string
  awayTeam: string
  homeFlag: string
  awayFlag: string
  expectedGoals: { home: number; away: number }
  outcomeProbabilities: { home: number; draw: number; away: number }
  likelyScore: string
  scoreStars: 0 | 1 | 2 | 3
  scoreProbabilities: ScoreProbability[]
  coverage: number
  weather: string
  altitude: number
  missingData: string[]
  factors: FactorContribution[]
  lineupImpact?: LineupImpact[]
  intelligence?: IntelligenceEvent[]
  simulation?: SimulationQuality | null
  quotes: MarketQuote[]
}

export interface TicketLeg {
  matchId: string
  label: string
  market: MarketType
  selection: string
  odds: number
}

export interface Ticket {
  id: string
  type: '单关' | '2串1' | '3串1' | '比分'
  legs: TicketLeg[]
  stake: number
  combinedOdds: number
  modelProbability: number
  robustExpectedReturn: number
  potentialPayout: number
}

export interface DistributionPoint {
  bankroll: number
  probability: number
}

export interface Portfolio {
  key: StrategyKey
  name: string
  subtitle: string
  stake: number
  retainedCash: number
  expectedProfit: number
  profitProbability: number
  lossProbability: number
  worstCase95: number
  p05: number
  median: number
  p95: number
  maxPayout: number
  stopProbability?: number
  medianMaxDrawdown?: number
  simulationPaths?: number
  simulationMode?: 'shared_score_paths' | 'no_tickets'
  strategyRules?: string[]
  tickets: Ticket[]
  distribution: DistributionPoint[]
}

export interface BacktestMetric {
  label: string
  value: string
  note: string
  status: 'good' | 'neutral' | 'warning'
}

export interface DailyForecast {
  schemaVersion: number
  generatedAt: string
  targetDate: string
  timezone: 'Asia/Shanghai'
  modelVersion: string
  pipelineVersion?: string
  dataSnapshot?: {
    id: string
    cutoff: string
    files: Array<{ path: string; sha256: string; bytes: number }>
  }
  reproducibility?: { baselineFrozen: boolean; randomSeed: number }
  simulationQuality?: {
    actualPaths: number
    seed: number
    parameterUncertainty: string
    groupRankProbabilities?: Record<string, Record<string, number[]>>
  }
  simulations: number
  bankroll: number
  oddsFreshMinutes: number
  overallCoverage: number
  status: 'ready' | 'degraded' | 'blocked'
  statusMessage: string
  matches: MatchForecast[]
  portfolios: Portfolio[]
  evidence: SourceEvidence[]
  backtest: BacktestMetric[]
}

export interface LedgerEntry {
  id: string
  createdAt: string
  targetDate: string
  strategy: StrategyKey
  openingBalance: number
  stake: number
  closingBalance?: number
  status: 'pending' | 'settled' | 'void'
  tickets: Ticket[]
  note?: string
}

export interface BankrollLedger {
  schemaVersion: 1
  initialBankroll: number
  entries: LedgerEntry[]
}

export interface MatchSettlement {
  matchId: string
  homeScore: number
  awayScore: number
  halfTimeHomeScore?: number | null
  halfTimeAwayScore?: number | null
  settledAt: string
}

export interface SettlementFile {
  generatedAt: string
  matches: MatchSettlement[]
}
