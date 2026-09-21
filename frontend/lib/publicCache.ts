export const NO_STORE_HEADERS = {'Cache-Control': 'no-store'} as const;

// Public responses are identical for every visitor. Keep browsers honest about
// freshness while letting Vercel absorb repeat reads before they reach Supabase.
export const PUBLIC_CACHE_HEADERS = {
  live: {
    'Cache-Control': 'no-store',
    'Vercel-CDN-Cache-Control': 'public, s-maxage=30, stale-while-revalidate=30',
  },
  status: {
    'Cache-Control': 'no-store',
    'Vercel-CDN-Cache-Control': 'public, s-maxage=60, stale-while-revalidate=60',
  },
  research: {
    'Cache-Control': 'no-store',
    'Vercel-CDN-Cache-Control': 'public, s-maxage=300, stale-while-revalidate=300',
  },
  archive: {
    'Cache-Control': 'no-store',
    'Vercel-CDN-Cache-Control': 'public, s-maxage=900, stale-while-revalidate=3600',
  },
} as const;

export function signalCacheHeaders(view: string) {
  return view === 'qualified' ? PUBLIC_CACHE_HEADERS.live : PUBLIC_CACHE_HEADERS.research;
}
