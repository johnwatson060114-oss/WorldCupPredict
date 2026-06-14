import { CheckCircle2, CircleDollarSign } from 'lucide-react'

interface NoBetPanelProps {
  hasPositiveOptions: boolean
  choice: 'hold' | 'fun'
  onChoice: (choice: 'hold' | 'fun') => void
}

export function NoBetPanel({ hasPositiveOptions, choice, onChoice }: NoBetPanelProps) {
  return (
    <aside className="no-bet-panel panel">
      <div className="section-heading compact">
        <div>
          <h2>{hasPositiveOptions ? '纪律开关' : '今晚没有正期望选项'}</h2>
          <p>{hasPositiveOptions ? '即使有候选，也可以选择不下注' : '是否仍想参与？'}</p>
        </div>
      </div>
      <button className={choice === 'hold' ? 'choice active' : 'choice'} onClick={() => onChoice('hold')}>
        <span><CheckCircle2 size={18} /></span>
        <div><strong>不买，保留本金</strong><small>默认选择，符合长期纪律</small></div>
      </button>
      <button className={choice === 'fun' ? 'choice active fun' : 'choice fun'} onClick={() => onChoice('fun')}>
        <span><CircleDollarSign size={18} /></span>
        <div><strong>生成 2元娱乐方案</strong><small>不计入正期望推荐</small></div>
      </button>
      <p className="no-bet-foot">系统不会代购，也不会强制每天下注。</p>
    </aside>
  )
}
