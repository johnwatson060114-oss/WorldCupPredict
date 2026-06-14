const flagCodes: Record<string, string> = {
  '🇩🇪': 'DE', '🇨🇼': 'CW', '🇳🇱': 'NL', '🇯🇵': 'JP',
  '🇨🇮': 'CI', '🇪🇨': 'EC', '🇸🇪': 'SE', '🇹🇳': 'TN',
  '🇪🇸': 'ES', '🇨🇻': 'CV', '🇧🇪': 'BE', '🇪🇬': 'EG',
  '🇸🇦': 'SA', '🇺🇾': 'UY', '🇮🇷': 'IR', '🇳🇿': 'NZ',
  '🇩🇿': 'DZ', '🇦🇷': 'AR', '🇦🇺': 'AU', '🇦🇹': 'AT',
  '🇧🇦': 'BA', '🇧🇷': 'BR', '🇨🇦': 'CA', '🇨🇴': 'CO',
  '🇨🇩': 'CD', '🇭🇷': 'HR', '🇨🇿': 'CZ', '🇫🇷': 'FR',
  '🇬🇭': 'GH', '🇭🇹': 'HT', '🇮🇶': 'IQ', '🇯🇴': 'JO',
  '🇲🇽': 'MX', '🇲🇦': 'MA', '🇳🇴': 'NO', '🇵🇦': 'PA',
  '🇵🇾': 'PY', '🇵🇹': 'PT', '🇶🇦': 'QA', '🇸🇳': 'SN',
  '🇿🇦': 'ZA', '🇰🇷': 'KR', '🇨🇭': 'CH', '🇹🇷': 'TR',
  '🇺🇸': 'US', '🇺🇿': 'UZ',
}

export function Flag({ flag, large = false }: { flag: string; large?: boolean }) {
  const code = flagCodes[flag] ?? 'UN'
  return <span className={`country-flag flag-${code.toLowerCase()} ${large ? 'large' : ''}`} aria-label={code} />
}
