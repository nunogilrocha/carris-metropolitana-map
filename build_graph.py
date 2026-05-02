"""
Build a transfer graph from Carris Metropolitana GTFS data.

Steps:
 1. Load stops, routes (lines), trips (gives pattern_id per trip).
 2. For each pattern, pick one canonical trip; stream stop_times to get stop sequences.
 3. Cluster stops by physical proximity (~30m grid) into "places".
 4. Compute lines-per-place; hubs = places served by >= THRESHOLD distinct lines.
 5. For each line, walk its stops in pattern order; emit edges between consecutive hubs.
 6. Emit JSON for the viewer.
"""
import csv, json, sys, math
from collections import defaultdict, Counter

GTFS_DIR = "data/gtfs"
STOP_TIMES = "data/gtfs/stop_times.txt"
OUT = "docs/graph.json"
HUB_THRESHOLD = 5            # min distinct lines a place must serve to be a hub
GRID_DEG = 0.0003            # ~30m at Lisbon latitude (rough)

csv.field_size_limit(sys.maxsize)

# 1. stops --------------------------------------------------------------------
stops = {}
with open(f"{GTFS_DIR}/stops.txt", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            lat = float(r["stop_lat"]); lon = float(r["stop_lon"])
        except ValueError:
            continue
        stops[r["stop_id"]] = {
            "name": r["stop_name"],
            "lat": lat, "lon": lon,
            "municipality": r.get("municipality_name", ""),
        }
print(f"stops: {len(stops)}", file=sys.stderr)

# 2. routes -> line metadata --------------------------------------------------
# In this GTFS, each `line_id` may have multiple `route_id`s but typically one.
lines = {}
route_to_line = {}
with open(f"{GTFS_DIR}/routes.txt", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        lid = r["line_id"]
        route_to_line[r["route_id"]] = lid
        if lid not in lines:
            lines[lid] = {
                "id": lid,
                "short_name": r["line_short_name"],
                "long_name": r["line_long_name"],
                "color": "#" + r["route_color"],
                "text_color": "#" + r["route_text_color"],
            }
print(f"lines: {len(lines)}", file=sys.stderr)

# 3. trips -> pattern_id -> (line_id, canonical trip_id) ----------------------
pattern_line = {}                   # pattern_id -> line_id
pattern_trip = {}                   # pattern_id -> chosen trip_id
line_patterns = defaultdict(list)   # line_id -> [pattern_id, ...]
with open(f"{GTFS_DIR}/trips.txt", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        pid = r["pattern_id"]; tid = r["trip_id"]; rid = r["route_id"]
        lid = route_to_line.get(rid)
        if lid is None:
            continue
        if pid not in pattern_trip:
            pattern_trip[pid] = tid
            pattern_line[pid] = lid
            line_patterns[lid].append(pid)
print(f"patterns: {len(pattern_trip)}", file=sys.stderr)

# Build reverse: trip_id -> pattern_id (only for canonical trips)
canonical_trip_to_pattern = {tid: pid for pid, tid in pattern_trip.items()}

# 4. stream stop_times.txt; keep only canonical trips -------------------------
# Group by trip_id, ordered by stop_sequence.
pattern_stops = defaultdict(list)   # pattern_id -> [(seq, stop_id)]
print("streaming stop_times.txt...", file=sys.stderr)
n = 0
with open(STOP_TIMES, encoding="utf-8") as f:
    rdr = csv.DictReader(f)
    for r in rdr:
        tid = r["trip_id"]
        pid = canonical_trip_to_pattern.get(tid)
        if pid is None:
            continue
        try:
            seq = int(r["stop_sequence"])
        except ValueError:
            continue
        pattern_stops[pid].append((seq, r["stop_id"]))
        n += 1
        if n % 500000 == 0:
            print(f"  {n} kept rows", file=sys.stderr)
print(f"kept stop_time rows: {n}", file=sys.stderr)

for pid in pattern_stops:
    pattern_stops[pid].sort()

# 5. cluster stops by lat/lon grid into "places" ------------------------------
def grid_key(lat, lon):
    return (round(lat / GRID_DEG), round(lon / GRID_DEG))

place_of_stop = {}
places = {}     # place_id -> {names: Counter, lat, lon, stop_ids: set}
for sid, s in stops.items():
    k = grid_key(s["lat"], s["lon"])
    if k not in places:
        places[k] = {
            "id": f"p{len(places)}",
            "names": Counter(),
            "lat_sum": 0.0, "lon_sum": 0.0, "n": 0,
            "stop_ids": set(),
            "municipality": s["municipality"],
        }
    p = places[k]
    p["names"][s["name"]] += 1
    p["lat_sum"] += s["lat"]; p["lon_sum"] += s["lon"]; p["n"] += 1
    p["stop_ids"].add(sid)
    place_of_stop[sid] = p["id"]

# finalise places
final_places = {}
for k, p in places.items():
    pid = p["id"]
    final_places[pid] = {
        "id": pid,
        "name": p["names"].most_common(1)[0][0],
        "lat": p["lat_sum"] / p["n"],
        "lon": p["lon_sum"] / p["n"],
        "municipality": p["municipality"],
        "line_ids": set(),  # filled below
    }
print(f"places after clustering: {len(final_places)}", file=sys.stderr)

# 6. For each line, build ordered list of places it visits --------------------
# Use the longest pattern as canonical (most stops -> most informative).
line_place_seq = {}    # line_id -> [place_id, ...] in order, deduped consecutively
for lid, pids in line_patterns.items():
    best = max(pids, key=lambda p: len(pattern_stops.get(p, [])))
    seq = []
    last = None
    for _, sid in pattern_stops.get(best, []):
        plid = place_of_stop.get(sid)
        if plid is None or plid == last:
            continue
        seq.append(plid)
        last = plid
        final_places[plid]["line_ids"].add(lid)
    line_place_seq[lid] = seq

# 7. Two edge sets: hub-collapsed and granular (consecutive places) -----------
edges_hub = defaultdict(lambda: {"lines": set()})   # between hubs only
edges_all = defaultdict(lambda: {"lines": set()})   # between consecutive places
hub_ids = {pid for pid, p in final_places.items() if len(p["line_ids"]) >= HUB_THRESHOLD}
print(f"hubs (>= {HUB_THRESHOLD} lines): {len(hub_ids)}", file=sys.stderr)

for lid, seq in line_place_seq.items():
    # granular edges: consecutive places along the line
    for a, b in zip(seq, seq[1:]):
        if a == b: continue
        edges_all[tuple(sorted((a, b)))]["lines"].add(lid)
    # hub-collapsed edges: only hops between consecutive hubs
    hub_seq = [pid for pid in seq if pid in hub_ids]
    for a, b in zip(hub_seq, hub_seq[1:]):
        if a == b: continue
        edges_hub[tuple(sorted((a, b)))]["lines"].add(lid)

print(f"edges hub: {len(edges_hub)}, edges all: {len(edges_all)}", file=sys.stderr)

# 8. Keep only places that are part of at least one line's path ---------------
used = set()
for (a, b) in edges_all:
    used.add(a); used.add(b)
kept_places = {pid: final_places[pid] for pid in used}
print(f"places kept (on at least one line): {len(kept_places)}", file=sys.stderr)

# 9. Emit JSON ---------------------------------------------------------------
import os
os.makedirs(os.path.dirname(OUT), exist_ok=True)
nodes = []
for pid, p in kept_places.items():
    nodes.append({
        "id": pid,
        "name": p["name"],
        "lat": p["lat"], "lon": p["lon"],
        "municipality": p["municipality"],
        "line_count": len(p["line_ids"]),
        "line_ids": sorted(p["line_ids"]),
        "is_hub": pid in hub_ids,
    })
edges_hub_list = [{"a": a, "b": b, "lines": sorted(e["lines"])}
                  for (a, b), e in edges_hub.items()]
edges_all_list = [{"a": a, "b": b, "lines": sorted(e["lines"])}
                  for (a, b), e in edges_all.items()]

# per-line ordered place sequence (for client-side route-finding)
line_paths = {lid: seq for lid, seq in line_place_seq.items() if seq}

out = {
    "lines": list(lines.values()),
    "nodes": nodes,
    "edges_hub": edges_hub_list,
    "edges_all": edges_all_list,
    "line_paths": line_paths,
    "meta": {
        "hub_threshold": HUB_THRESHOLD,
        "grid_deg": GRID_DEG,
        "total_lines": len(lines),
        "total_stops": len(stops),
        "total_places": len(final_places),
    },
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"wrote {OUT}: {os.path.getsize(OUT)} bytes", file=sys.stderr)
