# Dora Maar — Artistic Legacy & Online Findability

## Context
Research project to document Dora Maar's complete known catalog and measure how well each work is represented online. The output is a Jupyter notebook that builds the catalog from structured public APIs, simulates a Google search to see what artworks surface, and assigns each work an **impressions proxy** (Google Trends 0–100 interest score) — the scalar the user wants.

True Google Search Console impressions are not publicly accessible for third-party sites. The closest free proxy is **Google Trends** via `pytrends`, which returns a relative interest score (0–100) per keyword. This will be supplemented with **Wikipedia pageview counts** (7-day) where a page exists, since those are public and correlate with search impressions.

---

## Output
A single Jupyter notebook (`dora_maar_catalog.ipynb`) with:
- **Section 1** — Full catalog DataFrame (title, year, medium, institution, source)
- **Section 2** — Google-visible artworks (what surfaces for "Dora Maar" searches)
- **Section 3** — Impressions score per artwork (Google Trends + Wikipedia pageviews)
- **Section 4** — Ranked combined table, sortable, with a bar chart

---

## Data Sources for the Catalog

### 1. Wikidata SPARQL (free, structured)
Query: all works where `P170` (creator) = `Q236161` (Dora Maar).
Endpoint: `https://query.wikidata.org/sparql`
Returns: item ID, title (en/fr), year, medium, institution, Wikidata URL.

### 2. Met Museum API (free JSON, no key needed)
Search: `https://collectionapi.metmuseum.org/public/collection/v1/search?q=Dora+Maar&artistOrCulture=true`
Then fetch each object ID for full metadata. Returns ~24 items.

### 3. Artsy API (free public tier, app registration needed)
Endpoint: `https://api.artsy.net/api/artists/{id}/artworks`
Artsy artist slug: `dora-maar`. Returns structured artwork records with images.

### 4. Wikipedia / Wikimedia Commons scrape
Parse the category `Category:Photographs_by_Dora_Maar` via MediaWiki API to catch works not in other databases.

---

## Data Sources for Google-Visible Artworks
Use `WebSearch` / SerpAPI-style query for:
- `"Dora Maar" artwork`
- `"Dora Maar" photography`
- `Dora Maar site:en.wikipedia.org`
- `Dora Maar site:artsy.net`

Extract the artwork titles that appear in top 20 results per query. This defines the "Google-visible" set.

---

## Impressions Metric per Artwork

### Primary: Google Trends (`pytrends`)
```python
from pytrends.request import TrendReq
pytrends = TrendReq()
pytrends.build_payload(["Père Ubu Dora Maar", "Dora Maar Shell Hand"], timeframe="today 12-m")
df = pytrends.interest_over_time()
# Take mean score per keyword as the impressions proxy (0–100)
```

### Secondary: Wikipedia Pageviews API
For artworks that have a Wikipedia article:
`https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/all-agents/{title}/daily/{start}/{end}`

### Combined score
`impressions_score = trends_score * 0.7 + normalized_pageviews * 0.3`

---

## Implementation Steps

1. **Notebook setup** — install deps (`pytrends`, `SPARQLWrapper`, `requests`, `pandas`, `plotly`)
2. **Wikidata query** — SPARQL for creator=Q236161, parse results into DataFrame
3. **Met Museum query** — search API → fetch each object → append to DataFrame
4. **Artsy query** — authenticate with client ID/secret → fetch artworks → append
5. **Deduplicate** — normalize titles, drop duplicates by (title, year)
6. **Google search simulation** — run 4 search queries, extract artwork names from snippets/titles
7. **Google Trends scoring** — batch artwork names (5 per call, pytrends limit) → get mean interest
8. **Wikipedia pageviews** — look up pageviews for artworks with known Wikipedia pages
9. **Combine & rank** — merge scores, compute combined impressions score, sort descending
10. **Visualize** — horizontal bar chart of top 30 artworks by impressions score

---

## Critical Files
- `dora_maar_catalog.ipynb` — the notebook to create (at `/Users/pietro/Desktop/`)

## Key Libraries
- `SPARQLWrapper` — Wikidata SPARQL
- `requests` — Met/Artsy/Wikipedia APIs
- `pandas` — DataFrame operations
- `pytrends` — Google Trends proxy for impressions
- `plotly` / `matplotlib` — visualization

## Caveats to Note in Notebook
- Google Trends scores are relative (max in period = 100), not absolute impression counts
- No complete catalog raisonné exists; this catalog is best-effort from public APIs
- Picasso's portraits *of* Dora Maar are excluded (they are his works, not hers) unless explicitly flagged
- The 2019 Centre Pompidou retrospective catalog (500+ works, print only) is the most complete source but not machine-readable

## Verification
- Catalog should have ≥ 30 unique works (expect 50–100 across all sources)
- Known works should appear: "Père Ubu", "Shell-Hand / Untitled (Hand-Shell)", "Le Simulateur", "29 rue d'Astorg"
- Each artwork row has a non-null impressions score
- Bar chart renders without error
- Google-visible artworks list ≥ 10 items
