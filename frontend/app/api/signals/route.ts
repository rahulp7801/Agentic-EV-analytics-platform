import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import {createHash} from 'crypto';
import {unstable_cache} from 'next/cache';
import {databaseQuery,hosted} from '@/lib/database';
import {forecastPage,forecastRequest,FORECAST_PAGE_QUERY,type ForecastPageInput} from '@/lib/forecastPage';
import {NO_STORE_HEADERS,signalCacheHeaders} from '@/lib/publicCache';

export const dynamic='force-dynamic';

const cachedForecastPage=unstable_cache(async(pattern:string,profileKeys:string[],view:string,limit:number,offset:number)=>{
  const result=await databaseQuery<{data:ForecastPageInput}>(FORECAST_PAGE_QUERY,
    [pattern,profileKeys,view,view==='library' ? limit : 5001,offset],'forecast_page');
  if(!result.rows[0]?.data) throw new Error('Missing forecast page');
  return result.rows[0].data;
},['forecast-page-v1'],{revalidate:60});

export async function GET(request:Request) {
  let options:ReturnType<typeof forecastRequest>;
  try {options=forecastRequest(new URL(request.url));}
  catch {return NextResponse.json({error:'Unsupported forecast request.'},{status:400,headers:NO_STORE_HEADERS});}
  try {
    let data:ForecastPageInput;
    if(hosted) {
      const profileKeys=options.sport ? ['player-profiles:'+options.sport] : ['player-profiles:nfl','player-profiles:nba'];
      data=await cachedForecastPage(options.sport ? `signals:${options.sport}:%` : 'signals:%',profileKeys,
        options.view,options.limit,options.offset);
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
      if(options.view!=='library') data.rows=signals.map((signal:unknown)=>({payload:{...snapshot,signals:[signal]}}));
    }
    if(options.revision && options.revision!==data.revision) {
      return NextResponse.json({error:'Forecasts changed during browsing. Refresh to reload.'},{status:409,headers:NO_STORE_HEADERS});
    }
    return NextResponse.json(forecastPage(data,options),{headers:signalCacheHeaders(options.view)});
  } catch {
    return NextResponse.json({error:'Results are temporarily unavailable.',signals:[]},{status:503,headers:NO_STORE_HEADERS});
  }
}
