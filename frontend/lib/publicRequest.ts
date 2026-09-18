const PARAMETERS:Record<string,string[]>={
  '/api/signals':['sport','view','offset','limit','revision'],
  '/api/gamelogs':['sport','player','limit','before','exact'],
  '/api/metrics':['sport','cohort'],
  '/api/markets':['sport'], '/api/prop-screens':['sport'],
  '/api/games':['sport'], '/api/slate':['sport'], '/api/benchmarks':['sport'],
  '/api/scans':[], '/api/scan':[],
};

/** Reject unbounded/ambiguous requests before opening a database connection. */
export function publicRequest(request:Pick<Request,'url'|'method'|'headers'>):number|null {
  const url=new URL(request.url);
  if(!url.pathname.startsWith('/api/')) return null;
  if(!['GET','HEAD'].includes(request.method)) return request.method==='POST' && url.pathname==='/api/scan' ? 403 : 405;
  if(request.url.length>2048) return 414;
  if(request.headers.get('sec-fetch-site')==='cross-site') return 403;
  const allowed=PARAMETERS[url.pathname];
  if(!allowed) return 404;
  const seen=new Set<string>();
  for(const [key,value] of url.searchParams) {
    if(!allowed.includes(key) || seen.has(key) || value.length>128 || /[\u0000-\u001f]/.test(value)) return 400;
    seen.add(key);
  }
  return null;
}
