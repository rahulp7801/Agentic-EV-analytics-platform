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

export function metricInterval(metrics: Record<string, unknown>, key: string,
  percent = false, unit = '%') {
  const raw = metrics[key];
  if (!Array.isArray(raw) || raw.length !== 2
      || raw.some(value => typeof value !== 'number' || !Number.isFinite(value))) {
    return 'Unavailable';
  }
  const [lower, upper] = raw as number[];
  if (lower > upper) return 'Unavailable';
  const scale = percent ? 100 : 1;
  const digits = percent ? 1 : 3;
  return `${(lower * scale).toFixed(digits)}–${(upper * scale).toFixed(digits)}${percent ? unit : ''}`;
}
