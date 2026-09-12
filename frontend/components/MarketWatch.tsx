'use client';
import { useEffect, useState } from 'react';
import type { Sport } from '@/lib/types';
import {marketCoverageText,propQuoteCoverageText,type MarketCoverage,type PropQuoteCoverage} from '@/lib/marketCoverage';

interface Observation {
  captured_at: string;
  scope: string;
  sources: Record<string,{status:string;count:number;partial_coverage:boolean;
    coverage?:(MarketCoverage & Partial<PropQuoteCoverage> & {discovery_complete:boolean;omitted_markets:number;
      prop_discovery_complete?:boolean;prop_series_observed?:number;prop_series_expected?:number;prop_open_markets?:number;prop_open_events?:number;prop_linked_markets?:number;prop_linked_events?:number;prop_player_resolved_quote_markets?:number})}>;
  comparisons: {identity:string;kind:string;title:string;gross_cost:string;gross_gap_to_one_dollar:string;
    reasons:string[];legs:{book:string;team:string;cost:string;observed_at:string}[];
    exchange_fee_scenarios?:{combined_cost:{direct:string;non_direct:string};scope:string; schedule_effective_date:string};
    depth_fee_scenarios?:{cases:{contracts_per_kalshi_leg:number;combined_cost:{direct:string;non_direct:string}}[];scope:string}}[];
}

interface PropFunnel {
  kalshi_quotes:number;kalshi_exact_markets:number;kalshi_paired_sides:number;
  kalshi_missing_ask_sides:number;kalshi_missing_sportsbook_sides:number;
  kalshi_observation_skew_sides:number;
}

interface PropScreen {status:string;coverage:Partial<PropFunnel>}

function hasPropFunnel(value:Partial<PropFunnel>):value is PropFunnel {
  return ['kalshi_quotes','kalshi_exact_markets','kalshi_paired_sides','kalshi_missing_ask_sides',
    'kalshi_missing_sportsbook_sides','kalshi_observation_skew_sides'].every(
      key=>typeof value[key as keyof PropFunnel] === 'number');
}

export default function MarketWatch({sport}:{sport:Sport}) {
  const [data,setData] = useState<Observation|null>(null);
  const [error,setError] = useState('');
  const [propScreen,setPropScreen] = useState<PropScreen|null>(null);
  const [propError,setPropError] = useState('');
  const [now,setNow] = useState(Date.now());
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(''); setPropScreen(null); setPropError('');
    async function load() {
      try {
        const response=await fetch('/api/markets?sport='+sport,{signal:controller.signal,cache:'no-store'});
        const body=await response.json();
        if (!response.ok) throw new Error(body.error || 'Market observations unavailable.');
        setData(body);setError('');setNow(Date.now());
      } catch (error) {
        if (!controller.signal.aborted) {setError(error instanceof Error ? error.message : 'Market observations unavailable.');setNow(Date.now());}
      }
    }
    async function loadProps() {
      try {
        const response=await fetch('/api/prop-screens?sport='+sport,{signal:controller.signal,cache:'no-store'});
        const body=await response.json();
        if (!response.ok) throw new Error(body.error || 'Cross-venue prop scan unavailable.');
        setPropScreen(body);setPropError('');
      } catch (error) {
        if (!controller.signal.aborted) {
          setPropScreen(null);setPropError(error instanceof Error ? error.message : 'Cross-venue prop scan unavailable.');
        }
      }
    }
    void load();
    void loadProps();
    const timer=setInterval(()=>{void load();void loadProps();},30000);
    return ()=>{controller.abort();clearInterval(timer);};
  },[sport]);
  return <section style={{padding:16,height:'100%',overflow:'auto'}}>
    <h2>Market comparisons</h2>
    <p>Sportsbooks · Kalshi · PrizePicks — observation and research only</p>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p>Loading observations…</p>}
    {data && <>
      <p>{data.scope}</p>
      <p>Collection finished {new Date(data.captured_at).toLocaleString()}. Quote freshness is shown for each comparison.</p>
      <ul>{Object.entries(data.sources).map(([name,source])=><li key={name}>
        {name}: {source.status} · {source.count} source records{source.partial_coverage ? ' · partial coverage' : ''}
        {source.coverage && <span> · {marketCoverageText(source.coverage)}
          {!source.coverage.discovery_complete && ' · discovery incomplete'}
          {source.coverage.omitted_markets>0 && ` · ${source.coverage.omitted_markets} markets omitted`}</span>}
        {source.coverage?.prop_series_expected !== undefined && <span>
          {' '}· {source.coverage.prop_linked_markets} open player props linked across {source.coverage.prop_linked_events} game/series events
          {source.coverage.prop_structured_quote_markets !== undefined && <> · {propQuoteCoverageText(source.coverage as PropQuoteCoverage)}</>}
          {source.coverage.prop_player_resolved_quote_markets !== undefined && ` · ${source.coverage.prop_player_resolved_quote_markets} player identities resolved`}
          {' '}· {source.coverage.prop_series_observed}/{source.coverage.prop_series_expected} core prop series inventoried
          {!source.coverage.prop_discovery_complete && ' · prop discovery incomplete'}
        </span>}
      </li>)}</ul>
      <p>Positive gross gaps are screening leads, not profit. PrizePicks requires a complete entry payout; projection lines alone cannot establish an arbitrage.</p>
      {propScreen && hasPropFunnel(propScreen.coverage) && <p>
        Cross-venue prop pairing ({propScreen.status}): {propScreen.coverage.kalshi_exact_markets}/{propScreen.coverage.kalshi_quotes} Kalshi markets matched an exact sportsbook market;{' '}
        {propScreen.coverage.kalshi_paired_sides}/{2*propScreen.coverage.kalshi_exact_markets} complementary sides were paired. Unpaired sides: {propScreen.coverage.kalshi_missing_ask_sides} missing Kalshi asks,{' '}
        {propScreen.coverage.kalshi_missing_sportsbook_sides} missing sportsbook sides, {propScreen.coverage.kalshi_observation_skew_sides} outside the 30-second observation window.
      </p>}
      {propError && <p>Cross-venue prop scan: {propError}</p>}
      {data.comparisons.length===0 && <p>No comparisons could be built from this capture.</p>}
      {data.comparisons.map(row=>{
        const age=now-Math.min(...row.legs.map(leg=>Date.parse(leg.observed_at)));
        return <article className="card" key={row.kind+row.identity} style={{padding:12,marginBottom:10}}>
        <strong>{row.title}</strong> · {row.kind.replaceAll('_',' ')} · Unverified
        <p>{Number.isFinite(age) && age>=0 && age<=30000 ? 'Recent observations' : 'Stale observations — refresh required'}</p>
        <p>Cost per $1 binary payoff: ${Number(row.gross_cost).toFixed(4)} · gross gap: ${Number(row.gross_gap_to_one_dollar).toFixed(4)}</p>
        <ul>{row.legs.map((leg,index)=><li key={index}>{leg.book}: {leg.team} · ${Number(leg.cost).toFixed(4)} · observed {new Date(leg.observed_at).toLocaleTimeString()}</li>)}</ul>
        {row.exchange_fee_scenarios && <>
          <p>Cost including modeled exchange fees: ${Number(row.exchange_fee_scenarios.combined_cost.direct).toFixed(4)} for a direct account;
            {' '}${Number(row.exchange_fee_scenarios.combined_cost.non_direct).toFixed(4)} for a non-direct account.</p>
          <p>{row.exchange_fee_scenarios.scope}</p>
        </>}
        {row.depth_fee_scenarios && <>
          <p>Modeled cost at displayed depth:</p>
          {row.depth_fee_scenarios.cases.length ? <ul>{row.depth_fee_scenarios.cases.map(scenario=><li key={scenario.contracts_per_kalshi_leg}>
            {scenario.contracts_per_kalshi_leg} contracts per Kalshi leg: ${Number(scenario.combined_cost.direct).toFixed(4)} direct;
            {' '}${Number(scenario.combined_cost.non_direct).toFixed(4)} non-direct (combined cost of all legs).
          </li>)}</ul> : <p>Insufficient displayed depth for the requested sizes.</p>}
          <p>{row.depth_fee_scenarios.scope}</p>
        </>}
        <p>{row.reasons.join(' ')}</p>
      </article>;})}
    </>}
  </section>;
}
