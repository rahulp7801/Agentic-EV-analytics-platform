export const CURRENT_MARKET_WINDOW_MS = 90 * 60_000;

export type MarketFreshness = 'current' | 'stale' | 'unavailable';

export function marketFreshness(
  capturedAt: string | null | undefined,
  now = Date.now(),
): MarketFreshness {
  if (!capturedAt || !Number.isFinite(now)) return 'unavailable';
  const captured = Date.parse(capturedAt);
  if (!Number.isFinite(captured)) return 'unavailable';
  const age = now - captured;
  return age >= 0 && age <= CURRENT_MARKET_WINDOW_MS ? 'current' : 'stale';
}
