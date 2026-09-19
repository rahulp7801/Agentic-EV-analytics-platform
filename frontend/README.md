# Linework web interface

The Next.js application has two surfaces:

- `/` is the public product introduction. Its pipeline readout comes from the sanitized `/api/scans` endpoint.
- `/terminal` is the read-only research workspace for recorded estimates, outcomes, market comparisons, dependence bounds, and manual Kelly scenarios.

The interface never inserts example market data. Empty, stale, partial, and unavailable states remain explicit. The Kelly and scenario tools calculate only from inputs supplied by the user or from eligible recorded estimates.

Motion is the sole runtime animation library. Fonts are installed locally through Fontsource, and reduced-motion preferences are honored.

Run locally from this directory:

```sh
npm ci
npm run dev
```

Verify changes with:

```sh
npm test
npx tsc --noEmit
npm run lint
npm run build
```

Server routes use `DATABASE_URL` from the server environment. Never expose database or provider credentials through `NEXT_PUBLIC_` variables. See the repository root README and `.env.example` for the complete environment contract.
