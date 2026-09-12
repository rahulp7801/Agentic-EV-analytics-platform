export type MetricCohort = 'all' | 'recommendations';

export function metricCohort(url: string): MetricCohort | null {
  const value = new URL(url).searchParams.get('cohort') ?? 'all';
  return value === 'all' || value === 'recommendations' ? value : null;
}

export function metricSnapshotKey(cohort: MetricCohort) {
  return `metrics:${cohort}`;
}

export function metricLedgerArgs(cohort: MetricCohort) {
  return ['-m', 'sportsbet.ledger', ...(cohort === 'recommendations' ? ['--recommendations-only'] : [])];
}
