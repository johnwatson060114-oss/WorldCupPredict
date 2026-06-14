export const percent = (value: number, digits = 0) => `${(value * 100).toFixed(digits)}%`

export const signedPercent = (value: number, digits = 1) => {
  const percentage = value * 100
  return `${percentage >= 0 ? '+' : ''}${percentage.toFixed(digits)}%`
}

export const money = (value: number) => `${value >= 0 ? '' : '-'}${Math.abs(value).toFixed(0)}元`

export const beijingTime = (iso: string) =>
  new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(iso))

export const shortDateTime = (iso: string) =>
  new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(iso))
