"""Everything that makes one business run, as a radial map.

Michael, 2026-11-02: "a network of everything that's making this product
run ... here's everything that's running everything ... a way to quickly see
what holes do we have ... to truly be able to answer all questions from any
of the business partners: do we have a process in place for X?" And what
belongs on it: "the thing we don't need is anything explaining how messages
get sent to each other inside the app ... but how does this product let our
customers know there's an outage? That is connected to a system outside the
app itself." An outcome is something the product does that leans on a
system outside the app, answered by the lines to those systems.

The business sits in the middle. Around it, on the first ring, the SURFACES
people touch: the marketing site, the app, the portals, the phone apps, the
status site, the admin board. Behind each surface, on the second ring, the
SERVICES that power it, each drawn once and placed between the surfaces it
serves. Further out, the OUTCOMES a partner asks about, each wired to what
delivers it. On the outside, the AUDIENCES: who uses what. Every line is an
edge with its why, which the hover shows.

Placement is by angle: a surface takes an even slice of the circle; anything
else sits at the mean angle of what it is connected to, on its own ring, and
things on a ring that would overlap are pushed apart. Deterministic, so the
same business draws the same map every time and two businesses compare.

Holes still come from the business playbook: an essential need no service
fills is drawn as an empty slot on the services ring, in the sector of the
admin board, because that is where the owner goes to fill it.

Pure: takes rows, returns the dicts the page draws.
"""
import math

KIND_COLOR = {
    "audience": "#f8fafc",
    "surface": "#a78bfa",
    "service": "#38bdf8",
    "outcome": "#34d399",
    "hole": "#f59e0b",
    "center": "#c4b5fd",
}
STATUS_COLOR = {
    "delivered": "#34d399", "in_progress": "#fbbf24", "missing": "#f87171",
    "live": "#34d399", "building": "#fbbf24", "planned": "#94a3b8",
    "running": "#34d399", "setting_up": "#fbbf24",
}
# Each kind of surface is a concept of the icon vocabulary (Handbook, Icons);
# the map draws it from there.
SURFACE_GLYPH = {
    "site": "website", "app": "web-app", "portal": "portal", "phone": "phone-app",
    "status": "status-page", "admin": "admin-board", "inbox": "mail", "other": "web-app",
}

# Rings, in map units from the centre. A tile is 64 wide with its labels
# under it, an outcome pill about 220 wide, so the gaps between rings are
# what keep lines from running through labels.
RING = {"surface": 300, "service": 540, "outcome": 760, "audience": 960}
NODE_WIDTH = {"surface": 170, "service": 150, "outcome": 230, "audience": 160, "hole": 150}
CENTER = (1120, 1060)


def _mean_angle(angles):
    if not angles:
        return None
    x = sum(math.cos(a) for a in angles)
    y = sum(math.sin(a) for a in angles)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return angles[0]
    return math.atan2(y, x)


def _spread(items, radius, width):
    """Push nodes on one ring apart until none overlap, keeping their order.

    The minimum gap is the node width as an angle at this radius. Relaxation
    rather than arithmetic, because a crowded sector must borrow room from an
    empty one without reshuffling who sits next to whom. When the ring cannot
    hold them all at that width they are spaced evenly instead.
    """
    n = len(items)
    if n < 2:
        return
    gap = min(width / radius, 2 * math.pi / n)
    for _ in range(300):
        items.sort(key=lambda d: d["angle"])
        moved = False
        for i in range(n):
            a, b = items[i], items[(i + 1) % n]
            d = (b["angle"] - a["angle"]) if i < n - 1 else (b["angle"] + 2 * math.pi - a["angle"])
            if d < gap - 1e-6:
                push = (gap - d) / 2
                a["angle"] -= push
                b["angle"] += push
                moved = True
        if not moved:
            break


def layout(business, nodes, edges, needs=(), need_links=()):
    """The whole map for `business`.

    nodes       BusinessNode rows (audience, surface, service, outcome)
    edges       BusinessEdge rows, each with its why
    needs       every BusinessNeed, for the holes
    need_links  every BusinessNeedLink: the connection that follows between
                two services whose needs the playbook joins, with its why,
                drawn unless the business wrote its own line for the pair
    """
    cx, cy = CENTER
    by_id = {n.id: n for n in nodes}
    out = {}

    def add(key, kind, **fields):
        d = {"key": key, "kind": kind, "angle": None, "x": None, "y": None, "neighbours": []}
        d.update(fields)
        out[key] = d
        return d

    add("center", "center", name=business.label, role=business.name, mark=getattr(business, "map_mark", None),
        initials=business.initials, status="", status_label="", url=business.admin_url or "",
        color=KIND_COLOR["center"], glyph="", runbook="", runbook_missing=False, need="", need_slug="")

    for n in nodes:
        add(f"n{n.id}", n.kind, id=n.id, name=n.display_name, role=n.role or "", status=n.status or "",
            status_label=n.status_label, url=n.url or "", notes=n.notes or "", initials=n.initials,
            mark=n.mark_url, runbook=n.runbook_url,
            need=(n.need.name if n.need else ""), need_slug=(n.need.slug if n.need else ""),
            runbook_missing=(n.kind == "service" and n.playbook_id is None
                             and not (n.need is not None and n.need.in_house)),
            glyph=SURFACE_GLYPH.get(n.surface_kind or "other", "web-app") if n.kind == "surface" else "",
            color=(STATUS_COLOR.get(n.status or "", KIND_COLOR[n.kind]) if n.kind == "outcome"
                   else KIND_COLOR[n.kind]))

    # Holes: an essential need no service fills.
    filled = {n.need_id for n in nodes if n.kind == "service" and n.need_id}
    holes = []
    for need in needs:
        if need.essential and need.id not in filled:
            holes.append(add(f"h{need.id}", "hole", id=need.id, name=need.name, role=need.description or "",
                             status="missing", status_label="Missing", need=need.name, need_slug=need.slug,
                             suggestions=need.suggestions, url="", mark=None, initials="+", runbook="",
                             runbook_missing=False, color=KIND_COLOR["hole"], glyph=""))

    # Edges: the business's own, then the playbook's between two services
    # whose needs it joins, unless the business already drew that pair.
    drawn = {}
    for e in edges:
        a, b = by_id.get(e.from_node_id), by_id.get(e.to_node_id)
        if a is None or b is None or a.id == b.id:
            continue
        pair = tuple(sorted((a.id, b.id)))
        drawn[pair] = {"a": f"n{a.id}", "b": f"n{b.id}", "why": e.why or "", "derived": False, "id": e.id,
                       "kinds": tuple(sorted((a.kind, b.kind)))}
    services_by_need = {}
    for n in nodes:
        if n.kind == "service" and n.need_id:
            services_by_need.setdefault(n.need_id, []).append(n)
    for nl in need_links:
        for a in services_by_need.get(nl.from_need_id, []):
            for b in services_by_need.get(nl.to_need_id, []):
                pair = tuple(sorted((a.id, b.id)))
                if pair not in drawn and a.id != b.id:
                    drawn[pair] = {"a": f"n{a.id}", "b": f"n{b.id}", "why": nl.why or "", "derived": True,
                                   "kinds": ("service", "service")}
    for e in drawn.values():
        out[e["a"]]["neighbours"].append(e["b"])
        out[e["b"]]["neighbours"].append(e["a"])

    # Angles. Surfaces take even slices, from the top, in their sort order.
    surfaces = [out[f"n{n.id}"] for n in nodes if n.kind == "surface"]
    for i, s in enumerate(surfaces):
        s["angle"] = -math.pi / 2 + i * 2 * math.pi / max(1, len(surfaces))
    anchor = {s["key"]: s["angle"] for s in surfaces}
    admin = next((s for s in surfaces if s.get("glyph") == "admin-board"), surfaces[0] if surfaces else None)
    base = admin["angle"] if admin else -math.pi / 2

    def settle(kind, radius):
        ring = [d for d in out.values() if d["kind"] == kind]
        loose = []
        for d in ring:
            a = _mean_angle([anchor[k] for k in d["neighbours"] if k in anchor])
            if a is None:
                loose.append(d)
            else:
                d["angle"] = a
        # Nothing to lean on: spread through the admin board's sector.
        for i, d in enumerate(loose):
            d["angle"] = base + (i - (len(loose) - 1) / 2) * (NODE_WIDTH[kind] / radius)
        _spread(ring, radius, NODE_WIDTH[kind])
        for d in ring:
            anchor[d["key"]] = d["angle"]

    settle("service", RING["service"])
    if holes:
        for i, h in enumerate(holes):
            h["angle"] = base + (i - (len(holes) - 1) / 2) * (NODE_WIDTH["hole"] / RING["service"])
        ring = [d for d in out.values() if d["kind"] in ("service", "hole")]
        _spread(ring, RING["service"], NODE_WIDTH["service"])
        for d in ring:
            anchor[d["key"]] = d["angle"]
    settle("outcome", RING["outcome"])
    settle("audience", RING["audience"])

    for d in out.values():
        if d["kind"] == "center":
            d["x"], d["y"] = cx, cy
            continue
        r = RING["service"] if d["kind"] == "hole" else RING[d["kind"]]
        d["x"] = round(cx + r * math.cos(d["angle"]), 1)
        d["y"] = round(cy + r * math.sin(d["angle"]), 1)

    # Every surface hangs off the centre; the rest are the drawn pairs.
    out_edges = []
    for s in surfaces:
        out_edges.append({"a": "center", "b": s["key"], "why": s["role"] or "", "derived": True,
                          "kinds": ("center", "surface"), "color": KIND_COLOR["surface"]})
    for e in drawn.values():
        a, b = out[e["a"]], out[e["b"]]
        kinds = e["kinds"]
        if "outcome" in kinds:
            o = a if a["kind"] == "outcome" else b
            e["color"] = o["color"]
        elif "audience" in kinds:
            e["color"] = KIND_COLOR["audience"]
        elif "surface" in kinds:
            e["color"] = KIND_COLOR["surface"]
        else:
            e["color"] = KIND_COLOR["service"]
        out_edges.append(e)
    for e in out_edges:
        a, b = out[e["a"]], out[e["b"]]
        e["path"] = _path(a, b, cx, cy)
        e["label"] = f"{a['name']} and {b['name']}"
        e["outcome"] = "outcome" in e.get("kinds", ())
        e.pop("kinds", None)

    node_list = list(out.values())
    for d in node_list:
        d.pop("neighbours", None)
        d.pop("angle", None)
    return {
        "nodes": node_list,
        "edges": out_edges,
        "width": 2 * CENTER[0],
        "height": 2 * CENTER[1],
        "center": {"x": cx, "y": cy},
        "rings": RING,
        "legend": [{"kind": k, "label": l, "color": KIND_COLOR[k]} for k, l in
                   (("audience", "People"), ("surface", "What they use"),
                    ("service", "What powers it"), ("outcome", "What it delivers"), ("hole", "Hole"))],
        "counts": {
            "surfaces": len(surfaces),
            "services": sum(1 for n in nodes if n.kind == "service"),
            "audiences": sum(1 for n in nodes if n.kind == "audience"),
            "outcomes": sum(1 for n in nodes if n.kind == "outcome"),
            "gaps": sum(1 for n in nodes if n.kind == "outcome" and n.status != "delivered"),
            "holes": len(holes),
            "no_runbook": sum(1 for d in node_list if d["kind"] == "service" and d["runbook_missing"]),
            "edges": len(out_edges),
        },
    }


def _path(a, b, cx, cy):
    """A gentle curve between two nodes, bowed toward the centre.

    Straight spokes read as a wheel; a slight bow toward the middle keeps
    lines from stacking on the same radius and makes each one easy to
    follow with a pointer.
    """
    mx, my = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
    qx, qy = mx + (cx - mx) * 0.18, my + (cy - my) * 0.18
    return f"M {a['x']} {a['y']} Q {qx} {qy} {b['x']} {b['y']}"
