# Dashboard

React front end for the HK market-risk engine. See the main README, section "Dashboard".

```bash
npm install
npm run dev     # needs the API on :8000 (uv run uvicorn hkrisk.api.main:app --reload)
npm run build   # static files in dist/; set VITE_API_BASE when the API is on another origin
```

`src/api.ts` is the typed API client, `src/charts.tsx` the Recharts charts, `src/Chat.tsx`
the agent panel and `src/App.tsx` the page. Colours are CSS variables in `src/index.css`
(validated categorical palette; status red is reserved for VaR breaches).
