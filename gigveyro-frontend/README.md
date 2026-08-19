# GIGVEYRO Frontend

Production frontend for the GIGVEYRO payment gateway, built with Next.js App Router and TypeScript.

## Local setup

1. Copy `.env.example` to `.env.local`.
2. Start Backend V1 on `http://127.0.0.1:8000`.
3. Run `npm install` and `npm run dev`.

Authentication is proxied through Next.js route handlers. Access and refresh tokens are stored only in `HttpOnly` cookies and are never exposed to browser JavaScript.
