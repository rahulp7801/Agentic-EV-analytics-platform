import { NextRequest, NextResponse } from 'next/server';
import {publicRequest} from './lib/publicRequest';

export function proxy(request: NextRequest) {
  const status=publicRequest(request);
  if(status) return NextResponse.json({error:'Request rejected.'},{status,headers:{'Cache-Control':'no-store'}});
  if(request.nextUrl.pathname.startsWith('/api/')) return NextResponse.next();
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
  const development = process.env.NODE_ENV === 'development';
  const policy = `
    default-src 'self';
    script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ''};
    style-src 'self' 'nonce-${nonce}';
    style-src-attr 'unsafe-inline';
    img-src 'self' blob: data: https://a.espncdn.com;
    font-src 'self';
    connect-src 'self';
    worker-src 'self' blob:;
    media-src 'none';
    object-src 'none';
    base-uri 'self';
    form-action 'self';
    frame-src 'none';
    frame-ancestors 'none';
    manifest-src 'self';
    upgrade-insecure-requests;
  `.replace(/\s{2,}/g, ' ').trim();

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', policy);
  return response;
}

export const config = {
  matcher: [{
    source: '/((?!_next/static|_next/image|favicon.ico).*)',
  }],
};
