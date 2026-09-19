import {publicSignalSnapshots,publicPlayerProfile} from './signalMetrics.ts';
import {bestPickOptions} from './bestPicks.ts';
import type {Sport} from './types';

export const FORECAST_PAGE_SIZE=100;
const PAGE_BYTES=1024*1024;

export function forecastRequest(url:URL) {
  const sport=url.searchParams.get('sport');
  const view=url.searchParams.get('view') ?? 'library';
  const offset=url.searchParams.get('offset') ?? '0';
  const limit=url.searchParams.get('limit') ?? String(FORECAST_PAGE_SIZE);
  const revision=url.searchParams.get('revision');
  if((sport!==null && sport!=='nba' && sport!=='nfl' && sport!=='cfb') || !['library','qualified'].includes(view)
    // The public research window is deliberately capped at 1,000 rows. Larger
    // offsets add expensive cache keys without serving any product workflow.
    || !/^(0|[1-9][0-9]{0,3})$/.test(offset) || Number(offset)>=1000
    || !/^[1-9][0-9]{0,2}$/.test(limit) || Number(limit)>FORECAST_PAGE_SIZE
    || (revision!==null && !/^[a-f0-9]{64}$/.test(revision))
    || (view==='qualified' && (Number(offset)!==0 || revision!==null))) throw new Error('Invalid forecast request');
  return {sport:sport as Sport|null,view,offset:Number(offset),limit:Number(limit),revision};
}

// Flatten before transfer; retain the previous latest-100-game archive window.
export const FORECAST_PAGE_QUERY=`WITH latest AS MATERIALIZED (
  SELECT snapshot_key,payload,updated_at FROM dashboard_snapshots
  WHERE snapshot_key LIKE $1 AND ($3::boolean=false OR updated_at>=now()-interval '6 minutes')
  ORDER BY updated_at DESC,snapshot_key DESC LIMIT 100
), envelopes AS MATERIALIZED (
  SELECT snapshot_key,payload,updated_at,
    CASE WHEN jsonb_typeof(payload->'signals')='array' THEN payload->'signals' ELSE '[]'::jsonb END AS signals
  FROM latest
), indexed AS MATERIALIZED (
  SELECT *,jsonb_array_length(signals) AS signal_count,
    COALESCE(sum(jsonb_array_length(signals)) OVER (ORDER BY updated_at DESC,snapshot_key DESC
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0)::bigint AS base_offset
  FROM envelopes
), library_page AS (
  SELECT snapshot_key,payload->'generated_at' AS generated_at,signal,updated_at,ordinality
  FROM indexed CROSS JOIN LATERAL jsonb_array_elements(signals) WITH ORDINALITY AS items(signal,ordinality)
  WHERE $3::boolean=false AND base_offset<$5::bigint+$4::bigint AND base_offset+signal_count>$5::bigint
    AND base_offset+ordinality>$5::bigint AND base_offset+ordinality<=$5::bigint+$4::bigint
), qualified AS MATERIALIZED (
  SELECT snapshot_key,payload->'generated_at' AS generated_at,signal,updated_at,ordinality
  FROM envelopes CROSS JOIN LATERAL jsonb_array_elements(signals) WITH ORDINALITY AS items(signal,ordinality)
  WHERE $3::boolean=true AND signal->>'gated'='false'
), page AS (
  SELECT * FROM (
    SELECT * FROM library_page
    UNION ALL
    SELECT * FROM qualified
  ) candidates ORDER BY updated_at DESC,snapshot_key DESC,ordinality LIMIT $4
)
SELECT jsonb_build_object(
  'rows',COALESCE((SELECT jsonb_agg(jsonb_build_object('payload',jsonb_build_object(
      'generated_at',generated_at,'games','[]'::jsonb,'signals',jsonb_build_array(signal)))
    ORDER BY updated_at DESC,snapshot_key DESC,ordinality) FROM page),'[]'::jsonb),
  'profiles',COALESCE((SELECT jsonb_object_agg(snapshot_key,payload) FROM dashboard_snapshots
    WHERE snapshot_key=ANY($2::text[])),'{}'::jsonb),
  'total_count',(CASE WHEN $3::boolean THEN (SELECT count(*) FROM qualified)
    ELSE (SELECT COALESCE(sum(signal_count),0) FROM indexed) END),
  'window_complete',($3::boolean=false OR (SELECT count(*) FROM dashboard_snapshots
    WHERE snapshot_key LIKE $1 AND updated_at>=now()-interval '6 minutes')<=100),
  'revision',(SELECT encode(sha256(convert_to(COALESCE(string_agg(snapshot_key||':'||updated_at::text,','
    ORDER BY updated_at DESC,snapshot_key DESC),''),'UTF8')),'hex') FROM latest),
  'metadata',(SELECT jsonb_build_object('generated_at',payload->'generated_at','games','[]'::jsonb,
    'signals','[]'::jsonb) FROM latest ORDER BY updated_at DESC,snapshot_key DESC LIMIT 1),
  'invalid_envelopes',(SELECT count(*) FROM latest WHERE jsonb_typeof(payload->'signals') IS DISTINCT FROM 'array'
    OR jsonb_array_length(CASE WHEN jsonb_typeof(payload->'signals')='array'
      THEN payload->'signals' ELSE '[]'::jsonb END)>500)
) AS data`;

export type ForecastPageInput={rows:Array<{payload:unknown}>;profiles:Record<string,{profiles?:unknown}>;
  total_count:number;revision:string;metadata:unknown;invalid_envelopes:number;window_complete:boolean};

export function forecastPage(data:ForecastPageInput,request:ReturnType<typeof forecastRequest>,now=Date.now()) {
  if(data.invalid_envelopes!==0 || !Number.isSafeInteger(data.total_count) || data.total_count<0
    || data.total_count>50000 || !/^[a-f0-9]{64}$/.test(data.revision)
    || !Array.isArray(data.rows) || data.rows.length>(request.view==='qualified' ? 5001 : request.limit)) {
    throw new Error('Invalid forecast page');
  }
  if(request.revision && request.revision!==data.revision) throw new Error('Forecast revision changed');
  const metadata=publicSignalSnapshots(data.metadata ? [data.metadata] : [],now,request.sport ?? undefined);
  const signals:typeof metadata.signals=[];
  const games=new Map<string,typeof metadata.games[number]>();
  let consumed=0,invalid=0,bytes=0;
  for(const row of request.view==='qualified' ? data.rows.slice(0,5000) : data.rows) {
    const result=publicSignalSnapshots([row.payload],now,request.sport ?? undefined);
    if(result.signals.length>1) throw new Error('Invalid forecast row');
    let signal=result.signals[0];
    if(signal) {
      const values=data.profiles?.['player-profiles:'+signal.sport]?.profiles;
      if(Array.isArray(values) && values.length<=500) {
        const matches=values.map(value=>publicPlayerProfile(value,signal.sport,signal.player,now)).filter(Boolean);
        if(matches.length===1) signal={...signal,player_profile:matches[0]};
      }
      const size=new TextEncoder().encode(JSON.stringify(signal)).length;
      if(request.view==='library' && bytes+size>PAGE_BYTES && consumed>0) break;
      bytes+=size;signals.push(signal);
      for(const game of result.games) if(game.game_id===signal.game_id && game.sport===signal.sport) {
        games.set(game.sport+':'+game.game_id,game);
      }
    }
    invalid+=result.invalid_signals;consumed++;
  }
  const qualified=request.view==='qualified';
  const complete=request.offset+consumed>=data.total_count
    && (!qualified || (data.total_count<=5000 && data.window_complete===true));
  // An incomplete candidate inspection cannot advertise the strongest picks.
  const selected=qualified ? (complete ? bestPickOptions(signals,now) : []) : signals;
  return {generated_at:metadata.generated_at,games:qualified ? [] : [...games.values()],signals:selected,
    invalid_signals:invalid,total_count:data.total_count,
    pagination:{offset:request.offset,next_offset:!qualified && !complete ? request.offset+consumed : null,
      revision:data.revision,complete},research_window:'Latest 100 published game snapshots'};
}
