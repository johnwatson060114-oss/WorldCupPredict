import type { PersonalBetLeg } from './types'

export const PASS_DEFINITIONS = {
  '单关': { matches: 1, sizes: [1] },
  '2串1': { matches: 2, sizes: [2] },
  '3串1': { matches: 3, sizes: [3] },
  '3串3': { matches: 3, sizes: [2] },
  '3串4': { matches: 3, sizes: [2, 3] },
  '4串1': { matches: 4, sizes: [4] },
  '4串4': { matches: 4, sizes: [3] },
  '4串5': { matches: 4, sizes: [3, 4] },
  '4串6': { matches: 4, sizes: [2] },
  '4串11': { matches: 4, sizes: [2, 3, 4] },
  '5串1': { matches: 5, sizes: [5] },
  '5串5': { matches: 5, sizes: [4] },
  '5串6': { matches: 5, sizes: [4, 5] },
  '5串10': { matches: 5, sizes: [2] },
  '5串16': { matches: 5, sizes: [3, 4, 5] },
  '5串20': { matches: 5, sizes: [2, 3] },
  '5串26': { matches: 5, sizes: [2, 3, 4, 5] },
  '6串1': { matches: 6, sizes: [6] },
  '6串6': { matches: 6, sizes: [5] },
  '6串7': { matches: 6, sizes: [5, 6] },
  '6串15': { matches: 6, sizes: [2] },
  '6串20': { matches: 6, sizes: [3] },
  '6串22': { matches: 6, sizes: [4, 5, 6] },
  '6串35': { matches: 6, sizes: [2, 3] },
  '6串42': { matches: 6, sizes: [3, 4, 5, 6] },
  '6串50': { matches: 6, sizes: [2, 3, 4] },
  '6串57': { matches: 6, sizes: [2, 3, 4, 5, 6] },
  '7串1': { matches: 7, sizes: [7] },
  '7串7': { matches: 7, sizes: [6] },
  '7串8': { matches: 7, sizes: [6, 7] },
  '7串21': { matches: 7, sizes: [5] },
  '7串35': { matches: 7, sizes: [4] },
  '7串120': { matches: 7, sizes: [2, 3, 4, 5, 6, 7] },
  '8串1': { matches: 8, sizes: [8] },
  '8串8': { matches: 8, sizes: [7] },
  '8串9': { matches: 8, sizes: [7, 8] },
  '8串28': { matches: 8, sizes: [6] },
  '8串56': { matches: 8, sizes: [5] },
  '8串70': { matches: 8, sizes: [4] },
  '8串247': { matches: 8, sizes: [2, 3, 4, 5, 6, 7, 8] },
} as const

export type PassType = keyof typeof PASS_DEFINITIONS

export const PASS_GROUPS = [
  { label: '单关', options: ['单关'] },
  { label: '2关', options: ['2串1'] },
  { label: '3关', options: ['3串1', '3串3', '3串4'] },
  { label: '4关', options: ['4串1', '4串4', '4串5', '4串6', '4串11'] },
  { label: '5关', options: ['5串1', '5串5', '5串6', '5串10', '5串16', '5串20', '5串26'] },
  { label: '6关', options: ['6串1', '6串6', '6串7', '6串15', '6串20', '6串22', '6串35', '6串42', '6串50', '6串57'] },
  { label: '7关', options: ['7串1', '7串7', '7串8', '7串21', '7串35', '7串120'] },
  { label: '8关', options: ['8串1', '8串8', '8串9', '8串28', '8串56', '8串70', '8串247'] },
] as const satisfies ReadonlyArray<{ label: string; options: readonly PassType[] }>

export interface MatchSelectionGroup {
  matchId: string
  matchLabel: string
  legs: PersonalBetLeg[]
}

export const groupLegsByMatch = (legs: PersonalBetLeg[]): MatchSelectionGroup[] => {
  const groups = new Map<string, MatchSelectionGroup>()
  for (const leg of legs) {
    const current = groups.get(leg.matchId)
    if (current) current.legs.push(leg)
    else groups.set(leg.matchId, { matchId: leg.matchId, matchLabel: leg.matchLabel, legs: [leg] })
  }
  return [...groups.values()]
}

const elementarySum = (values: number[], size: number) => {
  const sums = Array(size + 1).fill(0) as number[]
  sums[0] = 1
  for (const value of values) {
    for (let index = size; index >= 1; index -= 1) sums[index] += sums[index - 1] * value
  }
  return sums[size]
}

export const ticketCountForPass = (legs: PersonalBetLeg[], passType: PassType) => {
  const definition = PASS_DEFINITIONS[passType]
  const selectionCounts = groupLegsByMatch(legs).map((group) => group.legs.length)
  return definition.sizes.reduce((sum, size) => sum + elementarySum(selectionCounts, size), 0)
}

export const stakeForPass = (legs: PersonalBetLeg[], passType: PassType, multiple: number) =>
  ticketCountForPass(legs, passType) * 2 * multiple

export const theoreticalMaxPayout = (legs: PersonalBetLeg[], passType: PassType, multiple: number) => {
  const definition = PASS_DEFINITIONS[passType]
  const maximumOdds = groupLegsByMatch(legs).map((group) => Math.max(...group.legs.map((leg) => leg.odds)))
  const payout = definition.sizes.reduce((sum, size) => sum + elementarySum(maximumOdds, size), 0) * 2 * multiple
  return Math.round(payout * 100) / 100
}

export const payoutForWinningOdds = (winningOddsByMatch: number[], passType: PassType, multiple: number) => {
  const definition = PASS_DEFINITIONS[passType]
  const payout = definition.sizes.reduce((sum, size) => sum + elementarySum(winningOddsByMatch, size), 0) * 2 * multiple
  return Math.round(payout * 100) / 100
}

export const inferPassType = (matchCount: number): PassType => {
  if (matchCount <= 1) return '单关'
  return `${Math.min(matchCount, 8)}串1` as PassType
}
