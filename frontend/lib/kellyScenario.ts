export interface KellyScenarioInput {
  probability: number;
  americanOdds: number;
  kellyFraction: number;
  bankroll: number;
  impliedProbability?: number;
}

export interface KellyScenarioResult {
  probability: number;
  impliedProbability: number;
  fullKelly: number;
  sizedFraction: number;
  expectedReturn: number;
  probabilityEdge: number;
  stake: number;
  winProfit: number;
  capped: boolean;
}

export function calculateKellyScenario(input: KellyScenarioInput): KellyScenarioResult | null {
  const { probability, americanOdds, kellyFraction, bankroll } = input;
  if (!Number.isFinite(probability) || probability <= 0 || probability >= 1
    || !Number.isFinite(americanOdds) || (americanOdds > -100 && americanOdds < 100)
    || !Number.isFinite(kellyFraction) || kellyFraction <= 0 || kellyFraction > 1
    || !Number.isFinite(bankroll) || bankroll <= 0
    || (input.impliedProbability !== undefined
      && (!Number.isFinite(input.impliedProbability) || input.impliedProbability <= 0 || input.impliedProbability >= 1))) {
    return null;
  }

  const profitMultiple = americanOdds > 0 ? americanOdds / 100 : 100 / Math.abs(americanOdds);
  const impliedProbability = input.impliedProbability
    ?? (americanOdds < 0
      ? Math.abs(americanOdds) / (Math.abs(americanOdds) + 100)
      : 100 / (americanOdds + 100));
  const fullKelly = Math.max((profitMultiple * probability - (1 - probability)) / profitMultiple, 0);
  const uncappedFraction = fullKelly * kellyFraction;
  const sizedFraction = Math.min(uncappedFraction, .25);
  const expectedReturn = probability * profitMultiple - (1 - probability);

  return {
    probability,
    impliedProbability,
    fullKelly,
    sizedFraction,
    expectedReturn,
    probabilityEdge: probability - impliedProbability,
    stake: sizedFraction * bankroll,
    winProfit: sizedFraction * bankroll * profitMultiple,
    capped: uncappedFraction > .25,
  };
}
