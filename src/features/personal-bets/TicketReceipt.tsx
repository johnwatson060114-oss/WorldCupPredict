import { Scissors, TicketCheck, X } from 'lucide-react'
import { groupLegsByMatch, type PassType } from './pass-types'
import { legMatchDate, ticketMatchDates } from './cross-day'
import type { PersonalBetLeg, PersonalBetStatus } from './types'

interface TicketReceiptProps {
  passType: PassType
  purchaseDate: string
  legs: PersonalBetLeg[]
  multiple: number
  ticketCount: number
  stake: number
  theoreticalPayout?: number
  payout?: number
  status?: PersonalBetStatus
  ticketId?: string
  compact?: boolean
  onRemoveLeg?: (leg: PersonalBetLeg) => void
}

const statusLabels: Record<PersonalBetStatus, string> = {
  pending: '待开奖',
  settled: '已开奖',
  void: '已作废',
}

const money = (value: number | undefined) => Number.isFinite(value) ? `${value!.toFixed(2)}元` : '--'

const receiptNumber = (purchaseDate: string, ticketId?: string) => {
  const date = purchaseDate.replaceAll('-', '') || '00000000'
  const suffix = (ticketId ?? 'preview').replaceAll('-', '').slice(0, 10).toUpperCase().padEnd(10, '0')
  return `${date}-${suffix}`
}

export function TicketReceipt({
  passType,
  purchaseDate,
  legs,
  multiple,
  ticketCount,
  stake,
  theoreticalPayout,
  payout,
  status = 'pending',
  ticketId,
  compact = false,
  onRemoveLeg,
}: TicketReceiptProps) {
  const groups = groupLegsByMatch(legs)
  const matchDates = ticketMatchDates(legs)

  return (
    <div className={compact ? 'sporttery-receipt compact' : 'sporttery-receipt'}>
      <header className="receipt-brand-row">
        <span className="receipt-brand-mark"><TicketCheck size={compact ? 18 : 24} /></span>
        <span><strong>中国体育彩票</strong><small>个人记录票 · 非官方购彩</small></span>
        <b>竞彩足球</b>
      </header>

      <div className="receipt-game">混合过关</div>
      <div className="receipt-pass-type">{passType}</div>
      <div className="receipt-date">出票日期：{purchaseDate || '---- -- --'}</div>
      {matchDates.length > 1 && <div className="receipt-cross-day">跨天串关 · {matchDates.map((date) => date.slice(5).replace('-', '/')).join(' + ')}</div>}

      <div className="receipt-divider" />
      <div className="receipt-leg-list">
        {groups.map((group, index) => (
          <div className="receipt-leg" key={group.matchId}>
            <span className="receipt-code">
              {group.legs[0].lotteryCode || `第${String(index + 1).padStart(2, '0')}场`}
              {legMatchDate(group.legs[0]) && <small>{legMatchDate(group.legs[0])!.slice(5).replace('-', '/')}</small>}
            </span>
            <span className="receipt-match">
              <b>{group.matchLabel}</b>
              <small>{group.legs.map((leg) => `${leg.market} ${leg.selection}`).join(' / ')}</small>
            </span>
            <span className="receipt-odds">{group.legs.map((leg) => leg.odds.toFixed(2)).join(' / ')}</span>
            {onRemoveLeg && <button type="button" onClick={() => group.legs.forEach(onRemoveLeg)} aria-label={`移除 ${group.matchLabel}`}><X size={14} /></button>}
          </div>
        ))}
        {!groups.length && <div className="receipt-empty">从左侧选择比赛和赔率后，这里会按真实票型生成票面。</div>}
      </div>
      <div className="receipt-divider" />

      <dl className="receipt-metrics">
        <div><dt>过关方式</dt><dd>{passType}</dd></div>
        <div><dt>倍数</dt><dd>{multiple || '--'}倍</dd></div>
        <div><dt>注数</dt><dd>{ticketCount ? `${ticketCount}注` : '--'}</dd></div>
        <div><dt>投注金额</dt><dd>{ticketCount ? money(stake) : '--'}</dd></div>
        <div><dt>{status === 'settled' ? '实际派彩' : '理论最高奖金'}</dt><dd>{status === 'settled' ? money(payout) : ticketCount ? money(theoreticalPayout) : '--'}</dd></div>
      </dl>

      <div className="receipt-number">票单编号：{receiptNumber(purchaseDate, ticketId)}</div>
      <div className="receipt-tear"><Scissors size={15} /></div>
      <div className="receipt-barcode" aria-hidden="true" />
      <footer className={`receipt-status ${status}`}>
        <strong>{statusLabels[status]}</strong>
        <span>感谢您为公益事业贡献力量</span>
      </footer>
    </div>
  )
}
