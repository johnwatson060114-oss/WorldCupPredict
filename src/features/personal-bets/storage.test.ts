import { beforeAll, describe, expect, it } from 'vitest'
import { personalBalance, settlePersonalLedger } from './storage'
import type { PersonalBetLedger, PersonalBetLeg } from './types'

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { setItem: () => undefined, getItem: () => null },
  })
})

const leg = (matchId: string): PersonalBetLeg => ({
  matchId,
  matchLabel: `${matchId} 主队 vs 客队`,
  market: '胜平负',
  selection: '胜',
  odds: 2,
})

describe('personal ledger settlement', () => {
  it('deducts a three-yuan pending bet from the available bankroll', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'three-yuan', createdAt: 'now', targetDate: '2026-06-16', matchLabel: 'A vs B',
        market: '胜平负', selection: '胜', odds: 2, stake: 3, standardStake: 2,
        decisionSource: 'subjective', status: 'pending', legs: [leg('m1')],
      }],
    }
    expect(personalBalance(ledger)).toBe(197)
  })

  it('scales payout to the actual amount paid instead of the standard two-yuan ticket', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'scaled', createdAt: 'now', targetDate: '2026-06-16', matchLabel: 'A vs B',
        market: '胜平负', selection: '胜', odds: 2, stake: 3, standardStake: 2,
        passType: '单关', multiple: 1, ticketCount: 1,
        decisionSource: 'subjective', status: 'pending', legs: [leg('m1')],
      }],
    }
    const settled = settlePersonalLedger(ledger, {
      generatedAt: 'now',
      matches: [{ matchId: 'm1', homeScore: 1, awayScore: 0, settledAt: 'now' }],
    })
    expect(settled.bets[0].payout).toBe(6)
    expect(personalBalance(settled)).toBe(203)
  })

  it('settles every winning child ticket inside a 4串11 system ticket', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'system-ticket',
        createdAt: '2026-06-14T20:00:00+08:00',
        purchaseDate: '2026-06-14',
        targetDate: '2026-06-15',
        matchLabel: '四场混合过关',
        market: '混合过关',
        selection: '四场主胜',
        odds: 1,
        stake: 22,
        passType: '4串11',
        multiple: 1,
        ticketCount: 11,
        decisionSource: 'subjective',
        status: 'pending',
        legs: ['a', 'b', 'c', 'd'].map(leg),
      }],
    }
    const settled = settlePersonalLedger(ledger, {
      generatedAt: 'now',
      matches: [
        { matchId: 'a', homeScore: 1, awayScore: 0, settledAt: 'now' },
        { matchId: 'b', homeScore: 2, awayScore: 0, settledAt: 'now' },
        { matchId: 'c', homeScore: 2, awayScore: 1, settledAt: 'now' },
        { matchId: 'd', homeScore: 0, awayScore: 1, settledAt: 'now' },
      ],
    })
    expect(settled.bets[0].status).toBe('settled')
    expect(settled.bets[0].payout).toBe(40)
  })

  it('checks archived closing odds before calculating the payout', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'verified-odds',
        createdAt: 'now',
        targetDate: '2026-06-18',
        matchLabel: 'Portugal vs DR Congo',
        market: '比分',
        selection: '1:1',
        odds: 9,
        stake: 2,
        standardStake: 2,
        passType: '单关',
        multiple: 1,
        ticketCount: 1,
        decisionSource: 'subjective',
        status: 'settled',
        payout: 18,
        legs: [{
          matchId: '2040182',
          matchLabel: 'Portugal vs DR Congo',
          market: '比分',
          selection: '1:1',
          odds: 9,
        }],
      }],
    }
    const settled = settlePersonalLedger(ledger, {
      generatedAt: 'now',
      matches: [{
        matchId: '2040182',
        homeScore: 1,
        awayScore: 1,
        settledAt: 'now',
        closingOdds: { 比分: { '1:1': 11 } },
        closingOddsSource: 'zgzcw.com',
        closingOddsCheckedAt: '2026-06-18T23:00:00+08:00',
      }],
    })
    expect(settled.bets[0].payout).toBe(22)
    expect(settled.bets[0].legs?.[0].settlementOdds).toBe(11)
    expect(settled.bets[0].oddsSource).toBe('zgzcw.com')
  })
})
