import { beforeAll, describe, expect, it } from 'vitest'
import { isWinningPersonalBet, personalBalance, reopenPersonalBet, settlePersonalBetManually, settlePersonalLedger } from './storage'
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
  it('marks only positive settled profit as a winning ticket', () => {
    expect(isWinningPersonalBet({ status: 'settled', stake: 10, payout: 18 })).toBe(true)
    expect(isWinningPersonalBet({ status: 'settled', stake: 10, payout: 10 })).toBe(false)
    expect(isWinningPersonalBet({ status: 'pending', stake: 10, payout: 18 })).toBe(false)
  })

  it('records manual profit and can reopen the ticket', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'manual',
        createdAt: 'now',
        targetDate: '2026-06-22',
        matchLabel: 'A vs B',
        market: '胜平负',
        selection: '胜',
        odds: 2,
        stake: 10,
        decisionSource: 'subjective',
        status: 'pending',
        legs: [leg('m1')],
      }],
    }
    const settled = settlePersonalBetManually(ledger, 'manual', 8)
    expect(settled.bets[0].status).toBe('settled')
    expect(settled.bets[0].payout).toBe(18)
    expect(settled.bets[0].settlementMode).toBe('manual')
    expect(personalBalance(settled)).toBe(208)

    const reopened = reopenPersonalBet(settled, 'manual')
    expect(reopened.bets[0].status).toBe('pending')
    expect(reopened.bets[0].payout).toBeUndefined()
    expect(personalBalance(reopened)).toBe(190)
  })

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

  it('keeps recording a negative bankroll instead of clamping at zero', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 20,
      modelSnapshots: [],
      bets: [{
        id: 'over-limit',
        createdAt: 'now',
        targetDate: '2026-06-22',
        matchLabel: 'A vs B',
        market: '胜平负',
        selection: '胜',
        odds: 2,
        stake: 35,
        decisionSource: 'subjective',
        status: 'pending',
        legs: [leg('m1')],
      }],
    }
    expect(personalBalance(ledger)).toBe(-15)
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

  it('matches a team-label leg to a numeric settlement id', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'label-id',
        createdAt: 'now',
        targetDate: '2026-06-19',
        matchLabel: 'Czechia vs South Africa',
        market: '比分',
        selection: '1:2',
        odds: 10,
        stake: 2,
        standardStake: 2,
        passType: '单关',
        multiple: 1,
        ticketCount: 1,
        decisionSource: 'subjective',
        status: 'pending',
        legs: [{
          matchId: 'Czechia vs South Africa',
          matchLabel: 'Czechia vs South Africa',
          market: '比分',
          selection: '1:2',
          odds: 10,
        }],
      }],
    }
    const settled = settlePersonalLedger(ledger, {
      generatedAt: 'now',
      matches: [{
        matchId: '2040235',
        matchLabel: 'Czechia vs South Africa',
        homeScore: 1,
        awayScore: 1,
        settledAt: 'now',
      }],
    })
    expect(settled.bets[0].status).toBe('settled')
    expect(settled.bets[0].payout).toBe(0)
  })

  it('corrects a reversed simulated handicap from archived official odds', () => {
    const ledger: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: '19645fc9-6110-47d2-9c41-aaf248123314',
        createdAt: '2026-06-21T04:02:53.419Z',
        targetDate: '2026-06-21',
        matchLabel: 'Tunisia vs Japan x Germany vs Ivory Coast',
        market: '混合过关',
        selection: 'reversed simulated handicaps',
        odds: 1.09,
        stake: 2,
        standardStake: 2,
        passType: '2串1',
        multiple: 1,
        ticketCount: 1,
        decisionSource: 'subjective',
        status: 'settled',
        payout: 2.18,
        legs: [
          { matchId: 'Tunisia vs Japan', matchLabel: 'Tunisia vs Japan', market: '让球胜平负', selection: '-2 负', odds: 1.01 },
          { matchId: 'Germany vs Ivory Coast', matchLabel: 'Germany vs Ivory Coast', market: '让球胜平负', selection: '+1 胜', odds: 1.08 },
        ],
      }],
    }
    const settled = settlePersonalLedger(ledger, {
      generatedAt: 'now',
      matches: [
        { matchId: '2040246', matchLabel: 'Tunisia vs Japan', homeScore: 0, awayScore: 4, settledAt: 'now' },
        {
          matchId: '2040244',
          matchLabel: 'Germany vs Ivory Coast',
          homeScore: 2,
          awayScore: 1,
          settledAt: 'now',
          closingOdds: { 让球胜平负: { '-1 胜': 1.98, '-1 平': 3.93, '-1 负': 2.7 } },
          closingOddsSource: 'zgzcw.com',
          closingOddsCheckedAt: 'now',
        },
        { matchId: 'Germany vs Ivory Coast', homeScore: 2, awayScore: 1, settledAt: 'now' },
      ],
    })
    expect(settled.bets[0].payout).toBe(0)
    expect(settled.bets[0].legs?.[1].settlementSelection).toBe('-1 胜')
    expect(settled.bets[0].legs?.[1].settlementOdds).toBe(1.98)
  })
})
