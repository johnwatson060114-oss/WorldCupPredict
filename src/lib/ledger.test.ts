import { describe, expect, it } from 'vitest'
import { settleLedger } from './ledger'
import type { BankrollLedger } from '../types'

describe('ledger settlement', () => {
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
})
