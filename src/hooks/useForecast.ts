import { useEffect, useState } from 'react'
import type { DailyForecast } from '../types'

export function useForecast() {
  const [data, setData] = useState<DailyForecast | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('./data/daily-forecast.json', { cache: 'no-store' })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<DailyForecast>
      })
      .then(setData)
      .catch((cause) => setError(cause instanceof Error ? cause.message : '预测数据读取失败'))
  }, [])

  return { data, error }
}
