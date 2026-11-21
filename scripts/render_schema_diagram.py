#!/usr/bin/env python3
"""Render reports/schema-diagram.svg straight from project-ddl-long.md (stdlib only).

The diagram is generated from the DDL itself, so it cannot drift from the implemented tables.
Usage:  python scripts/render_schema_diagram.py
"""
import os, re, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDL = os.path.join(ROOT, "project-ddl-long.md")
OUT = os.path.join(ROOT, "reports", "schema-diagram.svg")

# ------------------------------------------------------------------ parse the DDL (dw schema only)
md = open(DDL).read()
stmts = []
for block in re.findall(r"```sql(.*?)```", md, flags=re.S | re.I):
    block = re.sub(r"--[^\n]*", "", block)
    stmts += [s.strip() for s in block.split(";") if s.strip()]

tables = {}   # name -> dict(cols=[(name,type)], dist, sort)
for s in stmts:
    m = re.match(r"CREATE TABLE\s+dw\.(\w+)\s*\(", s, re.I)
    if not m:
        continue
    depth, i = 1, m.end()
    while depth:
        depth += {"(": 1, ")": -1}.get(s[i], 0)
        i += 1
    body, tail = s[m.end():i - 1], s[i:]
    cols = []
    for line in re.split(r",\s*\n", body):
        tok = line.strip().split()
        if tok and tok[0].upper() not in ("PRIMARY", "FOREIGN", "UNIQUE"):
            cols.append((tok[0], re.sub(r"\(.*", "", tok[1]).upper()))
    dist = re.search(r"DISTKEY\s*\(\s*(\w+)\s*\)", tail, re.I)
    sort = re.search(r"SORTKEY\s*\(\s*(\w+)\s*\)", tail, re.I)
    style = "ALL" if re.search(r"DISTSTYLE\s+ALL", tail, re.I) else ("KEY" if dist else "")
    tables[m.group(1)] = dict(cols=cols, dist=dist.group(1) if dist else None, sort=sort.group(1) if sort else None, style=style)

PK = {t: next(c for c, _ in v["cols"] if c.endswith("_sk") or c == "date_key") for t, v in tables.items()}
DIMS = [t for t in tables if t.startswith("dim_")]
FACTS = [t for t in tables if t.startswith("fact_")]

def target_dim(col):
    """Which dimension does a fact column reference?"""
    if col in ("order_date_key", "ship_date_key", "event_date_key"):
        return "dim_date"
    if col in ("from_customer_sk", "to_customer_sk", "customer_sk"):
        return "dim_customer"
    if col in ("from_product_sk", "to_product_sk", "product_sk"):
        return "dim_product"
    for d in DIMS:
        if PK[d] == col:
            return d
    return None

# ------------------------------------------------------------------ layout
ROW, HEAD, PAD, W_FACT, W_DIM = 15, 24, 8, 330, 215
def height(t): return HEAD + PAD + ROW * len(tables[t]["cols"]) + 20

pos = {}
big_dims = ["dim_date", "dim_customer", "dim_product"]
small_dims = [d for d in DIMS if d not in big_dims]
total_w = 1900
for k, d in enumerate(big_dims):
    pos[d] = (200 + k * 560, 30)
for k, f in enumerate(FACTS):
    pos[f] = (140 + k * 600, 330)
for k, d in enumerate(small_dims):
    pos[d] = (14 + k * 209, 790)
H = 790 + max(height(d) for d in small_dims) + 30
width = lambda t: W_FACT if t.startswith("fact_") else (W_DIM if t in big_dims else 198)

COLORS = {"fact_orders": "#2a7de1", "fact_events": "#e07b00", "fact_graph_edges": "#2e9e5b"}
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {H}" width="{total_w}" height="{H}" font-family="Helvetica,Arial,sans-serif" font-size="11">',
       f'<rect width="{total_w}" height="{H}" fill="#ffffff"/>',
       '<text x="20" y="18" font-size="15" font-weight="bold" fill="#222">Unified Commerce Data Warehouse - dw schema (generated from project-ddl-long.md)</text>']

def anchor(t, toward):
    x, y = pos[t]; w = width(t); h = height(t)
    cx, cy = x + w / 2, y + h / 2
    return (cx, y + h) if toward[1] > cy and abs(toward[1] - cy) > h / 2 else ((cx, y) if toward[1] < cy else (cx, cy))

# relationships first (drawn under boxes)
edges = []
for f in FACTS:
    for c, _ in tables[f]["cols"]:
        d = target_dim(c)
        if d and not c.startswith(("order_sk", "event_sk", "edge_sk")):
            edges.append((f, c, d))
spread = {}
for f, c, d in edges:
    fx, fy = pos[f]; dx, dy = pos[d]
    fh, dh = height(f), height(d)
    n = spread.setdefault((f, d), [])
    n.append(c)
    off = (len(n) - 1) * 6
    if dy < fy:   # dimension above the fact
        p1 = (fx + 40 + (list(FACTS).index(f) * 0) + off + 60 * (big_dims.index(d)), fy)
        p2 = (dx + 30 + off + 40 * FACTS.index(f), dy + dh)
    else:         # dimension below the fact
        p1 = (fx + 20 + 30 * small_dims.index(d) % (W_FACT - 40) + off, fy + fh)
        p2 = (dx + 99 + 10 * FACTS.index(f) - 10, dy)
    svg.append(f'<line x1="{p1[0]:.0f}" y1="{p1[1]:.0f}" x2="{p2[0]:.0f}" y2="{p2[1]:.0f}" stroke="{COLORS[f]}" stroke-width="1.2" opacity="0.55"/>')

# boxes
for t, info in tables.items():
    x, y = pos[t]; w = width(t); h = height(t)
    is_fact = t.startswith("fact_")
    head_fill = COLORS[t] if is_fact else "#4b5563"
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="#fafafa" stroke="{head_fill}" stroke-width="1.5"/>')
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{HEAD}" rx="5" fill="{head_fill}"/>')
    svg.append(f'<text x="{x + 8}" y="{y + 16}" font-size="12" font-weight="bold" fill="#fff">dw.{t}</text>')
    for k, (c, ty) in enumerate(info["cols"]):
        cy = y + HEAD + PAD + ROW * (k + 1) - 3
        is_pk = c == PK[t]
        is_fk = is_fact and target_dim(c) is not None and not is_pk
        tag = "PK" if is_pk else ("FK" if is_fk else "")
        wt = "bold" if (is_pk or is_fk) else "normal"
        svg.append(f'<text x="{x + 8}" y="{cy}" font-weight="{wt}" fill="#111">{html.escape(c)}</text>')
        svg.append(f'<text x="{x + w - 8}" y="{cy}" text-anchor="end" fill="#666">{html.escape(ty)} {tag}</text>')
    foot = f'DIST: {info["style"] or "AUTO"}' + (f'({info["dist"]})' if info["dist"] else "") + f' | SORT: {info["sort"] or "-"}'
    svg.append(f'<text x="{x + 8}" y="{y + h - 6}" font-size="10" fill="#555">{html.escape(foot)}</text>')

# legend
lx = 1500
svg.append(f'<text x="{lx}" y="{H - 90}" font-weight="bold">Relationships (fact FK -> dimension PK)</text>')
for k, (f, col) in enumerate(COLORS.items()):
    svg.append(f'<line x1="{lx}" y1="{H - 72 + k * 16}" x2="{lx + 28}" y2="{H - 72 + k * 16}" stroke="{col}" stroke-width="2"/>')
    svg.append(f'<text x="{lx + 36}" y="{H - 68 + k * 16}">{f}</text>')
svg.append("</svg>")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write("\n".join(svg))
print(f"wrote {OUT}: {len(tables)} tables ({len(FACTS)} facts, {len(DIMS)} dimensions), {len(edges)} fact->dimension relationships")
