/** 125.4 -> "02:05": simulated time as a clock. */
export function clockText(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  const mm = String(Math.floor(whole / 60)).padStart(2, '0')
  const ss = String(whole % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

/** 0.5 -> "0.5x", 2 -> "2x". */
export function speedText(rate: number): string {
  return `${Number.isInteger(rate) ? rate : rate.toString()}x`
}
