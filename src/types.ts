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
  oddsSource?: 'official' | 'simulated'
  formalEligible?: boolean
  formalBlockReason?: string | null
  marketConflict?: {
    status: 'clear' | 'conflict' | 'unavailable'
    blocked: boolean
    maxGap: number | null
    modelFavorite: string | null
    marketFavorite: string | null
    reason: string
  }
  observedAt: string
  kickoffBeijing?: string
  lotteryCode?: string
  matchDate?: string
}

export type FinalFourStage = 'SEMI_FINAL' | 'FINAL' | 'THIRD_PLACE'

export interface FinalFourContext {
  policy: 'world_cup_final_four_commentary_matrix_v2'
  predictionTarget: '90_minutes'
  stage: FinalFourStage
  stageSource: 'fixture_stage' | 'official_2026_beijing_schedule'
  applied: boolean
  matrixAdjustmentApplied: boolean
  diagnosticOnly: boolean
  validationStatus: string
  validationReason?: string
  stageParameters: {
    candidateTotalXgMultiplier: number
    candidateFirstHalfShare: number
    activeMatrixBlend: number
    coveragePenalty: number
    uncertaintyMultiplier: number
    valueProbabilityGap: number
    trainingMatches?: number
    rawCommentaryPaceMultiplier?: number
  }
  preStageExpectedGoals: { home: number; away: number }
  candidateExpectedGoals: { home: number; away: number }
  adjustedExpectedGoals: { home: number; away: number }
  coverageBefore: number
  coverageAfter: number
}

export interface FinalFourModel {
  policy: 'final_four_value_assessment_v1'
  predictionTarget: '90_minutes'
  stage: FinalFourStage
  confidence95: Record<Outcome, [number, number]>
  noVigMarketProbabilities: Record<Outcome, number> | null
  probabilityGaps: Record<Outcome, number> | null
  valueProbabilityGap: number
  valueSelections: Outcome[]
  status: 'value_identified' | 'no_clear_value' | 'market_unavailable'
  conclusion: string
  scoreMatrix: 'calibrated_regular_time_score_matrix'
  topScoreLimit: number
  riskFlags: {
    lineupUncertainty: boolean
    smallStageSample: boolean
    marketUsedAsIndependentAnchor: boolean
  }
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
  stage?: string | null
  predictionTarget?: '90_minutes' | null
  expectedGoals: { home: number; away: number }
  modelDecomposition?: {
    longTermExpectedGoals?: { home: number; away: number }
    objectiveFormNet?: { home: number; away: number }
    tacticalNet?: { home: number; away: number }
    groupStageFormNet?: { home: number; away: number }
    tournamentFormNet?: { home: number; away: number }
    preMotivationExpectedGoals?: { home: number; away: number }
    motivationNet?: { home: number; away: number }
    preKnockoutExpectedGoals?: { home: number; away: number }
    knockoutNet?: { home: number; away: number }
    adjustedExpectedGoals?: { home: number; away: number }
    totalGoalsProvider?: string
    strengthAllocator?: string
    allocationPolicy?: string
    eloAllocationWeight?: number
    allocationValidationSet?: string
    estimatedTotalGoals?: number
    formLayer?: string
    motivationLayer?: string
    knockoutLayer?: string
    preFinalFourExpectedGoals?: { home: number; away: number }
    finalFourLayer?: string
    finalFourStage?: FinalFourStage
    finalFourMatrixBlend?: number
    tournamentEvidence?: TournamentEvidence
    marketCalibration?: MarketCalibration
  }
  tournamentForm?: {
    sourceRound: string
    commentaryMode: 'text_only' | 'event_timeline' | 'minute_by_minute_events'
    applied: boolean
    home: TournamentFormSide
    away: TournamentFormSide
  } | null
  groupStageForm?: {
    sourceRound: string
    commentaryMode: 'minute_by_minute_events'
    applied: boolean
    home: TournamentFormSide
    away: TournamentFormSide
  } | null
  tournamentEvidence?: TournamentEvidence | null
  knockoutContext?: {
    policy: string
    favoriteSide: 'home' | 'away' | null
    xgNet: { home: number; away: number }
    adjustedExpectedGoals: { home: number; away: number }
    homeLatePressure: { attackMultiplier: number; defensiveRiskMultiplier: number }
    awayLatePressure: { attackMultiplier: number; defensiveRiskMultiplier: number }
    applied: boolean
  } | null
  finalFourContext?: FinalFourContext | null
  finalFourModel?: FinalFourModel | null
  scoreCalibration?: {
    applied: boolean
    reason?: string
    policy?: string
    profile?: string
    candidateProfile?: string
    intensity?: number
    candidateIntensities?: number[]
    validation?: Record<string, unknown> | null
    sourceKnockoutPolicy?: string
    favoriteSide?: 'home' | 'away' | null
    totalGoalWeights?: Record<string, number>
    expectedTotalGoalsBefore?: number
    expectedTotalGoalsAfter?: number
    outcomePreserved?: boolean
    maxCellDelta?: number
  }
  marketCalibration?: MarketCalibration | null
  outcomeProbabilities: { home: number; draw: number; away: number }
  halfFullSignal?: {
    applied: boolean
    policy: string
    role: string
    assistWeight: number
    topHalfFullSelection: string
    topHalfFullProbability: number
    outcomeSignal: { home: number; draw: number; away: number }
    assistedOutcomeProbabilities: { home: number; draw: number; away: number }
    outcomeDelta: { home: number; draw: number; away: number }
    maxOutcomeDelta: number
    note?: string
  }
  outcomeDecision?: {
    threshold: number
    maxProbability: number
    selection: Outcome
    status: 'recommended' | 'watch'
  }
  likelyScore: string
  scoreStars: 0 | 1 | 2 | 3
  scoreProbabilities: ScoreProbability[]
  totalGoalsCore?: {
    policy: string
    label: string
    selections: string[]
    probability: number
  }
  totalGoalsBoundaryRisk?: {
    policy: string
    triggered: boolean
    level: 'watch' | 'none'
    coreProbability: number
    adjacentSelection: string | null
    adjacentProbability: number
    thresholds: {
      maxCoreProbability: number
      minAdjacentProbability: number
    }
    reason: string
  }
  totalGoalsTailRisk?: {
    policy: string
    triggered: boolean
    level: 'tail_watch' | 'none'
    coreProbability: number
    threeProbability: number
    fourPlusProbability: number
    watchSelections: string[]
    thresholds: {
      maxLowCoreProbability: number
      minThreeProbability: number
      minFourPlusProbability: number
    }
    reason: string
  }
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

export interface TournamentEvidenceSide {
  team: string
  matchesUsed: number
  commentaryMatchesUsed: number
  effectiveWeight: number
  attackResidual: number
  defenseResidual: number
  outcomeAttackResidualDiagnostic: number
  outcomeDefenseResidualDiagnostic: number
  scoreResidualsDirectlyAdjustStrength: false
  halfTimeMatchesUsed: number
  firstHalfAttackResidual: number
  firstHalfDefenseResidual: number
  restDays: number | null
  extraTimeLoad: boolean
  post90LoadSeverity: number
  visibleFatigueEvents: number
  forcedInjurySubstitutions: number
  fatigueAttackDelta: number
  fatigueDefenseRiskDelta: number
  commentarySourceUrls: string[]
}

export interface TournamentEvidence {
  policy: 'current_tournament_commentary_evidence_v2'
  predictionTarget: '90_minutes'
  halfLifeMatches: number
  shrinkage: number
  commentaryProcessScale: number
  maxSideXgShift: number
  home: TournamentEvidenceSide
  away: TournamentEvidenceSide
  xgNet: { home: number; away: number }
  adjustedExpectedGoals: { home: number; away: number }
  applied: boolean
  diagnosticOnly?: boolean
  selectionReason?: string
  extraTimePolicy: '90_to_120_commentary_changes_next_match_load_only'
}

export interface MarketCalibration {
  applied: boolean
  policy: 'bounded_dual_axis_market_anchor_v1'
  reason?: string
  observedAt?: string | null
  strengthBlend?: number
  totalGoalsBlend?: number
  deViggedOutcomeProbabilities?: { home: number; draw: number; away: number } | null
  deViggedTotalGoalsProbabilities?: Record<string, number> | null
  marketExpectedTotalGoals?: number | null
  preCalibrationExpectedGoals?: { home: number; away: number }
  postCalibrationExpectedGoals?: { home: number; away: number }
  xgShift?: { home: number; away: number }
  totalXgShift?: number
  bounds?: { maxSideXgShift: number; maxTotalXgShift: number }
  sideCapHit?: boolean
  totalCapHit?: boolean
}

export interface TournamentFormSide {
  team: string
  attackDelta: number
  defenseDelta: number
  objectiveAttackDelta?: number
  objectiveDefenseDelta?: number
  tacticalAttackDelta?: number
  tacticalDefenseDelta?: number
  decay: number
  observedMatchday?: number
  observedMatchdays?: number[]
  targetMatchday: number
  confidence: number
  coverage?: number
  admissionStatus?: string
  objectiveAdmissionStatus?: string
  tacticalAdmissionStatus?: string
  credibilityLabels?: string[]
  summary: string
}

export interface FirstRoundSource {
  type: 'official_result' | 'text_match_centre'
  url: string
  publishedAt: string
  summary: string
  archivedText: boolean
}

export interface FirstRoundTeamProfile {
  team: string
  teamEn: string
  opponent: string
  matchId: string
  scoreFor: number
  scoreAgainst: number
  performanceStatus: 'above_expectation' | 'near_expectation' | 'below_expectation'
  summary: string
  evidenceConfidence: number
  dimensions: {
    attackCreation: number | null
    defensiveControl: number | null
    midfieldProgression: number | null
    transition: number | null
    setPieces: number | null
    goalkeeping: number | null
    stamina: number | null
    status: string
  }
  commentaryEvidence: {
    mode: 'text_only'
    archivedMinuteByMinute: boolean
    labels: string[]
    note: string
    sources: FirstRoundSource[]
  }
  objectiveForm: {
    attackDelta: number
    defenseDelta: number
    admissionStatus: 'enabled' | 'observation_only'
    redCardAdjusted: boolean
    finishingOutlierShrunk: boolean
    opponentStrengthAdjusted: boolean
    leadingStateAdjusted: boolean
  }
}

export interface FirstRoundReview {
  schemaVersion: number
  generatedAt: string
  round: {
    name: string
    completedLocalDate: string
    matches: number
    teams: number
    totalGoals: number
    averageGoals: number
    commentaryMode: 'text_only'
  }
  method: {
    stateCapPerTeamDirectionXg: number
    conversionWasFitOnFirstRound: boolean
    commentaryDirectlyChangesProbability: boolean
    missingTextPolicy: string
    productionPolicy: string
  }
  teams: FirstRoundTeamProfile[]
}

export interface TotalGoalsModelReview {
  generatedAt: string
  productionPolicy: string
  currentModel: ModelReviewSummary
  shadowModel: ModelReviewSummary
  tailShadowModel?: ModelReviewSummary & { reason?: string }
  strengthAllocationPolicy?: {
    eloAllocationWeight: number
    validationYears: string[]
    validationTournament: string
    validationMatches: number
    selectionRule: string
    excludedYears: string[]
  }
  adoptionDecision: {
    status: 'keep' | 'observe' | 'switch'
    should_switch_model: boolean
    recommendation_zh: string
    reason: string
    gates: Record<string, boolean>
  }
}

export interface ModelReviewSummary {
  role: string
  spec: string
  matches: number
  exact_accuracy: number
  core_accuracy: number
  average_log_loss: number
  average_rps?: number
  calibration_error?: number
}

export interface TicketLeg {
  matchId: string
  label: string
  market: MarketType
  selection: string
  odds: number
  kickoffBeijing?: string
  lotteryCode?: string
  matchDate?: string
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
  comboGroup?: {
    matchId: string
    market: MarketType
    size: number
    coveragePct: number
  }
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
  entertainmentMode?: boolean
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
  predictionTarget?: '90_minutes'
  finalFourPolicy?: {
    schemaVersion: number
    policy: string
    predictionTarget: '90_minutes'
    scoreMatrix: Record<string, unknown>
    stageProfiles: Record<FinalFourStage, FinalFourContext['stageParameters']>
    validation: Record<string, unknown>
  }
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
  parlayLookaheadDays?: number
  parlayMatches?: MatchForecast[]
  parlayCandidateMatches?: Array<{
    id: string
    lotteryCode: string
    kickoffBeijing: string
    homeTeam: string
    awayTeam: string
    coverage: number
  }>
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
  matchLabel?: string
  homeScore: number
  awayScore: number
  halfTimeHomeScore?: number | null
  halfTimeAwayScore?: number | null
  settledAt: string
  closingOdds?: Partial<Record<MarketType, Record<string, number>>>
  closingOddsSource?: string
  closingOddsIssue?: string
  closingOddsCheckedAt?: string
}

export interface SettlementFile {
  generatedAt: string
  matches: MatchSettlement[]
}
