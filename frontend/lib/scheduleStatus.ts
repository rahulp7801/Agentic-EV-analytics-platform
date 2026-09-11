export function scheduleSnapshot(data: Record<string,unknown> | null, now=Date.now()) {
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  const age=now-Date.parse(String(data?.captured_at ?? ''));
  if (!data || !Number.isFinite(age) || age<0 || age>90*60000 || data.as_of_date!==today
      || !['complete','partial'].includes(String(data.status)) || !Array.isArray(data.games)) {
    return {status:503,body:{games:[],partial:true,error:'Schedules are temporarily unavailable.'}};
  }
  return {status:200,body:{games:data.games,partial:data.status==='partial',captured_at:data.captured_at}};
}
