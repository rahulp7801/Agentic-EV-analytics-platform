import {publicSignalSnapshots} from './signalMetrics.ts';
import {bestPicks} from './bestPicks.ts';
import type {Sport} from './types';

/** Bounded pages, stable snapshot revision, explicit coverage; never silently complete. */
export async function fetchForecasts(sport:Sport,signal?:AbortSignal,view='library',fetchImpl=fetch) {
  let offset=0,revision:string|undefined,total=0,complete=false,invalid=0;
  const signals:ReturnType<typeof publicSignalSnapshots>['signals']=[];
  const games=new Map<string,ReturnType<typeof publicSignalSnapshots>['games'][number]>();
  let generated_at:string|null=null;
  // ponytail: render the latest 1,000 library rows; server-side archive search when larger histories are needed.
  while(offset<1000) {
    const params=new URLSearchParams({sport,view,offset:String(offset),limit:String(Math.min(100,1000-offset))});
    if(revision) params.set('revision',revision);
    const response=await fetchImpl('/api/signals?'+params,{cache:'no-store',signal});
    if(!response.ok) throw new Error('Forecasts unavailable');
    const body=await response.json();
    if(!Array.isArray(body.signals) || !Array.isArray(body.games) || body.games.length>100
      || !Number.isSafeInteger(body.invalid_signals ?? 0) || (body.invalid_signals ?? 0)<0
      || (body.invalid_signals ?? 0)>5000) throw new Error('Invalid forecast response');
    const empty=body.generated_at===null && body.signals.length===0 && body.games.length===0;
    const page=publicSignalSnapshots(empty ? [] : [{...body,games:[]}],Date.now(),sport);
    signals.push(...page.signals);invalid+=page.invalid_signals+(body.invalid_signals ?? 0);
    for(let index=0;index<body.games.length;index+=10) {
      const batch=publicSignalSnapshots([{...body,signals:[],games:body.games.slice(index,index+10)}],Date.now(),sport);
      for(const game of batch.games) games.set(game.sport+':'+game.game_id,game);
    }
    generated_at ??=page.generated_at;
    const pagination=body.pagination;
    // Rolling propagation may still serve the original, strictly validated deployment contract.
    if(pagination===undefined) {total=signals.length;complete=true;break;}
    if(!Number.isSafeInteger(body.total_count) || body.total_count<0 || body.total_count>50000
      || pagination.offset!==offset || !/^[a-f0-9]{64}$/.test(pagination.revision)
      || (revision && revision!==pagination.revision) || typeof pagination.complete!=='boolean'
      || (view==='library' && page.signals.length>100)) throw new Error('Invalid forecast coverage');
    total=body.total_count;revision=pagination.revision;complete=pagination.complete;
    if(view==='qualified') break;
    const next=pagination.next_offset;
    if(complete) {if(next!==null) throw new Error('Invalid forecast coverage');break;}
    if(!Number.isSafeInteger(next) || next<=offset || next>offset+100 || next>total) throw new Error('Invalid forecast cursor');
    offset=next;
  }
  return {signals:view==='qualified' ? (complete ? bestPicks(signals) : []) : signals,
    games:[...games.values()],game:null,generated_at,invalid_signals:invalid,total_count:total,complete};
}
