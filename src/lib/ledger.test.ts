import { describe, expect, it } from 'vitest'
import { combinedAvailableBalance, settleLedger } from './ledger'
import type { BankrollLedger } from '../types'
import type { PersonalBetLedger } from '../features/personal-bets/types'

describe('ledger settlement', () => {
  it('uses personal pending bets in the global available balance', () => {
    const ledger: BankrollLedger = { schemaVersion: 1, initialBankroll: 200, entries: [] }
    const personal: PersonalBetLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      modelSnapshots: [],
      bets: [{
        id: 'personal', createdAt: 'now', targetDate: '2026-06-16', matchLabel: 'A vs B',
        market: '胜平负', selection: '胜', odds: 2, stake: 3,
        decisionSource: 'subjective', status: 'pending',
      }],
    }
    expect(combinedAvailableBalance(ledger, personal)).toBe(197)
  })

  it('settles a -1 handicap only when the home side wins by two', () => {
    const ledger: BankrollLedger = {
      schemaVersion: 1,
      initialBankroll: 200,
      entries: [{
        id: 'entry', createdAt: '2026-06-14T18:00:00+08:00', targetDate: '2026-06-15',
        strategy: 'balanced', openingBalance: 200, stake: 10, status: 'pending',
        tickets: [{
          id: 'ticket', type: '单关', stake: 10, combinedOdds: 3, modelProbability: .4,
          robustExpectedReturn: .1, potentialPayout: 30,
          legs: [{ matchId: 'm1', label: 'A vs B', market: '让球胜平负', selection: '-1 胜', odds: 3 }],
        }],
      }],
    }
    const settled = settleLedger(ledger, { generatedAt: 'now', matches: [{ matchId: 'm1', homeScore: 2, awayScore: 0, settledAt: 'now' }] })
    expect(settled.entries[0].closingBalance).toBe(220)
  })

  it('settles total goals and half-full tickets from the real score split', () => {
    const ledger: BankrollLedger = {
      schemaVersion: 1, initialBankroll: 200,
      entries: [{
        id: 'entry-2', createdAt: 'now', targetDate: '2026-06-15', strategy: 'balanced',
        openingBalance: 200, stake: 4, status: 'pending', tickets: [
          { id: 't1', type: '单关', stake: 2, combinedOdds: 3, modelProbability: .4, robustExpectedReturn: .1, potentialPayout: 6, legs: [{ matchId: 'm1', label: 'A vs B', market: '总进球数', selection: '3', odds: 3 }] },
          { id: 't2', type: '单关', stake: 2, combinedOdds: 4, modelProbability: .3, robustExpectedReturn: .1, potentialPayout: 8, legs: [{ matchId: 'm1', label: 'A vs B', market: '半全场', selection: '平胜', odds: 4 }] },
        ],
      }],
    }
    const settled = settleLedger(ledger, { generatedAt: 'now', matches: [{ matchId: 'm1', homeScore: 2, awayScore: 1, halfTimeHomeScore: 0, halfTimeAwayScore: 0, settledAt: 'now' }] })
    expect(settled.entries[0].closingBalance).toBe(210)
  })
})
