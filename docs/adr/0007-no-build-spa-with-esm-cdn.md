# 0007. No-build SPA via ESM + CDN

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Two requirements collided. The admin panel should be a separate SPA — a clean boundary for
a future front-end team. And the project must avoid installing package managers and build
toolchains: no npm, no `node_modules`, no bundler.

A conventional React + Vite + npm setup satisfies the first and violates the second.
Loading React with Babel-standalone from a `<script>` tag satisfies neither well: it
transpiles JSX in the browser on every page load, and it requires `unsafe-eval` in the
Content Security Policy.

## Decision

React loaded as native ES modules from a CDN, with `htm` instead of JSX.

```html
<script type="importmap">
{ "imports": {
    "react":     "https://esm.sh/react@19.0.0",
    "react-dom": "https://esm.sh/react-dom@19.0.0",
    "htm":       "https://esm.sh/htm@3.1.1"
}}
</script>
```

Components are real `.js` files with `import`/`export`. No bundler, no build step, no
`node_modules`. `htm` uses tagged template literals, so **no `eval`** — the CSP stays
strict.

**Versions in import URLs are always pinned exactly.** An unpinned CDN URL means the CDN can
serve new code at any moment, and that code executes with the full privileges of a
logged-in store operator. That is an open supply-chain door into the admin panel. Pinned
versions, plus SRI where the CDN supports it.

## Consequences

**We gain:** a real SPA with a real team boundary, and zero toolchain to install or
maintain.

**We pay:**

- **No TypeScript checking and no tree-shaking.** Acceptable for an internal panel used by
  dozens of companies; it would not be acceptable for a public high-traffic site.
- **Lighthouse performance suffers.** An external origin costs DNS + TLS + extra round
  trips, and there is no bundling. Mitigated with `preconnect`, `modulepreload`, pinned
  versions (enabling immutable caching), and route-level dynamic `import()`. Accepted
  consciously.
- **The panel stops loading if the CDN is down.** A third party is now in the critical path
  of our admin tool.
- The SPA reintroduces **CORS** and browser-held session state, which the earlier
  server-rendered design avoided. Therefore: **no JWT in `localStorage`** — any XSS would
  steal a store operator's session. The panel authenticates with a server-side session
  behind a `__Host-` prefixed, `HttpOnly`, `Secure`, `SameSite` cookie plus a CSRF token.
  Only the Flutter app uses bearer tokens.

**Reversible.** Vendoring the ESM files into our own origin removes the CDN dependency, the
Lighthouse penalty, and the supply-chain exposure — while remaining zero-npm. If the costs
above start to bite, that is the move.
