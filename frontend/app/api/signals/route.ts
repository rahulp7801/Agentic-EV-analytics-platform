import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import {createHash} from 'crypto';
import {databaseQuery,hosted} from '@/lib/database';
import {forecastPage,forecastRequest,FORECAST_PAGE_QUERY,type ForecastPageInput} from '@/lib/forecastPage';

export const dynamic='force-dynamic';

export async function GET(request:Request) {
  let options:ReturnType<typeof forecastRequest>;
  try {options=forecastRequest(new URL(request.url));}
  catch {return NextResponse.json({error:'Unsupported forecast request.'},{status:400,headers:{'Cache-Control':'no-store'}});}
  try {
    let data:ForecastPageInput;
    if(hosted) {
      const profileKeys=options.sport ? ['player-profiles:'+options.sport] : ['player-profiles:nfl','player-profiles:nba'];
      const result=await databaseQuery<{data:ForecastPageInput}>(FORECAST_PAGE_QUERY,
        [options.sport ? `signals:${options.sport}:%` : 'signals:%',profileKeys,options.view==='qualified',
          options.view==='qualified' ? 5001 : options.limit,options.offset]);
      data=result.rows[0].data;
    } else {
      const paths=[path.join(process.cwd(),'public','signals_cache.json'),
        path.join(process.cwd(),'..','frontend','public','signals_cache.json')];
      const filePath=paths.find(value=>fs.existsSync(value));
      if(!filePath) throw new Error('No published snapshot');
      const raw=fs.readFileSync(filePath,'utf8');
      const snapshot=JSON.parse(raw);
      if(!Array.isArray(snapshot.signals) || snapshot.signals.length>500) throw new Error('Invalid snapshot');
      const signals=snapshot.signals.filter((value:{sport?:unknown;gated?:unknown})=>
        (!options.sport || value?.sport===options.sport) && (options.view!=='qualified' || value?.gated===false));
      data={rows:signals.slice(options.offset,options.offset+options.limit).map((signal:unknown)=>
        ({payload:{...snapshot,signals:[signal]}})),profiles:{},total_count:signals.length,
        revision:createHash('sha256').update(raw).digest('hex'),metadata:{...snapshot,signals:[],games:[]},invalid_envelopes:0,window_complete:true};
      if(options.view==='qualified') data.rows=signals.map((signal:unknown)=>({payload:{...snapshot,signals:[signal]}}));
    }
    if(options.revision && options.revision!==data.revision) {
      return NextResponse.json({error:'Forecasts changed during browsing. Refresh to reload.'},{status:409,headers:{'Cache-Control':'no-store'}});
    }
    return NextResponse.json(forecastPage(data,options),{headers:{'Cache-Control':'no-store','Vercel-CDN-Cache-Control':'public, s-maxage=10'}});
  } catch {
    return NextResponse.json({error:'Results are temporarily unavailable.',signals:[]},{status:503,headers:{'Cache-Control':'no-store'}});
  }
}
