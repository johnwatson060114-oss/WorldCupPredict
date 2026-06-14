import { Download, Landmark, Trash2, Upload } from 'lucide-react'
import { downloadLedger, currentBalance } from '../lib/ledger'
import { money, shortDateTime } from '../lib/format'
import type { BankrollLedger } from '../types'

interface LedgerPageProps {
  ledger: BankrollLedger
  onReset: () => void
  onImport: (ledger: BankrollLedger) => void
}

export function LedgerPage({ ledger, onReset, onImport }: LedgerPageProps) {
  const importFile = async (file: File | undefined) => {
    if (!file) return
    const parsed = JSON.parse(await file.text()) as BankrollLedger
    if (parsed.schemaVersion !== 1 || !Array.isArray(parsed.entries) || typeof parsed.initialBankroll !== 'number') {
      throw new Error('不支持的资金流水格式')
    }
    onImport(parsed)
  }
  return (
    <main className="content-page">
      <div className="page-title"><div><span>只保存在本机浏览器</span><h1>资金记录</h1></div></div>
      <section className="ledger-summary panel">
        <div><Landmark size={22} /><span>初始本金</span><strong>{ledger.initialBankroll}元</strong></div>
        <div><span>当前可用</span><strong>{money(currentBalance(ledger))}</strong></div>
        <div><span>已记录方案</span><strong>{ledger.entries.length}</strong></div>
        <div className="ledger-actions">
          <button onClick={() => downloadLedger(ledger)}><Download size={15} />导出 JSON</button>
          <label className="file-button"><Upload size={15} />导入 JSON<input type="file" accept="application/json" onChange={(event) => void importFile(event.target.files?.[0])} /></label>
          <button onClick={onReset}><Trash2 size={15} />清空记录</button>
        </div>
      </section>
      <section className="panel ledger-table-wrap">
        <table className="ledger-table">
          <thead><tr><th>记录时间</th><th>目标日期</th><th>策略</th><th>投入</th><th>票数</th><th>状态</th><th>赛后余额</th></tr></thead>
          <tbody>
            {ledger.entries.map((entry) => <tr key={entry.id}><td>{shortDateTime(entry.createdAt)}</td><td>{entry.targetDate}</td><td>{entry.strategy}</td><td>{entry.stake}元</td><td>{entry.tickets.length}</td><td>{entry.status}</td><td>{entry.closingBalance ?? '--'}</td></tr>)}
            {!ledger.entries.length && <tr><td colSpan={7} className="empty-row">尚未确认任何实际购买。预测方案不会自动写入本金流水。</td></tr>}
          </tbody>
        </table>
      </section>
    </main>
  )
}
