export const dynamic = 'force-dynamic';

// Scans consume paid provider credits and write audit data; only the worker may run them.
export async function POST() {
  return Response.json({error:'Market updates are managed automatically.'}, {status:403});
}

export async function GET() {
  return Response.json({scanning:false, managed:true, progress:null});
}
