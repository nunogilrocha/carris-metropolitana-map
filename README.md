# Carris Metropolitana — Bus Line Transfer Graph

An interactive, zoomable graph of Lisbon-area bus lines, showing where lines
intersect. Inspired by metro maps but for the ~700-line Carris Metropolitana
suburban network — far too dense for a static schematic.

Data source: official [Carris Metropolitana API](https://api.carrismetropolitana.pt/).

## What it shows

- **Nodes** = transfer hubs (a clustered "place" served by ≥ 5 distinct lines).
- **Edges** = direct hops between hubs along at least one line; thicker edges
  carry more shared lines.
- **Hover** a node or edge to see exactly which lines stop / share it.
- **Click** a line in the sidebar to highlight only that line's hops.

## Layout

Hubs are placed by their geographic centroid (lat/lon → flat projection). Not a
true Beck-style schematic, but readable, zoom-friendly, and good enough for
"which lines cross which where."

## Run locally

```sh
# 1. download GTFS + build the graph (~1 minute, downloads ~100 MB zip)
python3 build_graph.py

# 2. serve the viewer
cd docs && python3 -m http.server 8765
# open http://localhost:8765
```

Re-running `build_graph.py` regenerates `docs/graph.json` from a fresh GTFS
download.

## Tunable parameters

In `build_graph.py`:

- `HUB_THRESHOLD` — minimum lines a place must serve to become a hub (default `5`).
  Raise for a sparser, hub-only view; lower for more density.
- `GRID_DEG` — lat/lon grid size used to cluster nearby stops into a single
  "place" (default `0.0003` ≈ 30 m). Increase to merge more aggressively.

## Files

```
build_graph.py     # GTFS → graph.json
docs/              # served by GitHub Pages
  index.html       # self-contained D3 v7 viewer (single file)
  graph.json       # generated; ~540 KB
data/              # gitignored — cached GTFS files
```

The 882 MB `stop_times.txt` is extracted briefly during the build and deleted
after; only the small reference tables stay on disk.

## Deploying for free

The viewer is fully static — just `index.html` + `graph.json` + D3 from a CDN —
so it runs on any static host:

- **GitHub Pages**: enabled in this repo — Settings → Pages → branch `main`,
  folder `/docs`.
- **Cloudflare Pages / Netlify / Vercel**: connect the repo, set the publish
  directory to `docs/`, no build command.

To keep the graph fresh, regenerate `docs/graph.json` periodically and commit
it. A GitHub Actions cron job (e.g. weekly) running `build_graph.py` and
opening a PR with the updated JSON would automate this.
