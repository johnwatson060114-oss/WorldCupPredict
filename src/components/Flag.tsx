const flagCodes: Record<string, string> = {
  '🇩🇪': 'DE', '🇨🇼': 'CW', '🇳🇱': 'NL', '🇯🇵': 'JP',
  '🇨🇮': 'CI', '🇪🇨': 'EC', '🇸🇪': 'SE', '🇹🇳': 'TN',
  '🇪🇸': 'ES', '🇨🇻': 'CV', '🇧🇪': 'BE', '🇪🇬': 'EG',
  '🇸🇦': 'SA', '🇺🇾': 'UY', '🇮🇷': 'IR', '🇳🇿': 'NZ',
}

export function Flag({ flag, large = false }: { flag: string; large?: boolean }) {
  const code = flagCodes[flag] ?? 'UN'
  return <span className={`country-flag flag-${code.toLowerCase()} ${large ? 'large' : ''}`} aria-label={code} />
}
