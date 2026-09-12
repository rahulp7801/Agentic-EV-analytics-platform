export function rateInterval(metrics: Record<string, unknown>, key: string) {
  const raw = metrics[key];
  if (!Array.isArray(raw) || raw.length !== 2
      || raw.some(value => typeof value !== 'number' || !Number.isFinite(value))) {
    return 'Unavailable';
  }
  const [lower, upper] = raw as number[];
  if (lower < 0 || upper > 1 || lower > upper) return 'Unavailable';
  return `${(lower * 100).toFixed(1)}–${(upper * 100).toFixed(1)}%`;
}
