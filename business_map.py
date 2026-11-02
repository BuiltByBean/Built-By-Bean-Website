"""Everything that makes one business run, as a map.

Michael, 2026-11-02, of EntertainHQ: "the amount of services, aka playbooks,
that are making this whole thing run, I mean, it's insane. And I would just
love to see that mapping ... here's everything that's running everything ...
also a way to quickly see what holes do we have."

Two layers of truth feed it. The NEED is the business playbook: a thing every
business (or this kind of business) has to have, such as a bank account or a
domain, with the vendors that can fill it and the connections that follow
once two needs are both filled. The SERVICE is what one business actually
uses for a need: its vendor, with a runbook when the catalogue has one, and
what it is doing for this business in a sentence. A need with no service is a
HOLE, drawn as an empty slot, which is the second thing the map is for.

Pure: takes rows, returns the dicts the page draws. The layout is columns in
the order a business gets built, left to right, so the map reads the same way
a business playbook does, and every vendor lands in the same column on every
business's map. A force layout would be prettier for one business and
different for each, which is the wrong trade for a map meant to be compared.
"""

# Columns, in the order a business is built. The key is what a need carries.
LAYERS = (
    ("legal", "Legal", "#f59e0b"),
    ("money", "Money", "#10b981"),
    ("infrastructure", "Infrastructure", "#38bdf8"),
    ("product", "Product", "#a78bfa"),
    ("operations", "Operations", "#fb7185"),
    ("comms", "Comms", "#22d3ee"),
    ("growth", "Growth", "#a3e635"),
    ("intelligence", "Intelligence", "#e879f9"),
)
LAYER_INDEX = {key: i for i, (key, _label, _color) in enumerate(LAYERS)}
LAYER_LABEL = {key: label for key, label, _color in LAYERS}
LAYER_COLOR = {key: color for key, _label, color in LAYERS}

STATUSES = (
    ("running", "Running"),
    ("setting_up", "Setting up"),
    ("planned", "Planned"),
)
STATUS_LABEL = dict(STATUSES)

# Geometry, in SVG units. A node is a 56px mark (the icon at the size the
# Businesses tile draws it, with no box behind it) and its name underneath.
NODE_R = 32
COL_W = 240
ROW_H = 130
LEFT = 140
TOP = 120


def _sort_key(need):
    return (need.sort_order if need is not None else 10_000, need.name if need is not None else "")


def layout(business, needs, services, links, need_links):
    """The whole map for `business`.

    needs        every BusinessNeed in the catalogue
    services     this business's BusinessService rows
    links        this business's BusinessLink rows (explicit, with a why)
    need_links   every BusinessNeedLink (the template's connections)
    """
    need_by_id = {n.id: n for n in needs}

    # One node per service, and one per essential need nobody has filled.
    nodes = []
    for s in services:
        need = need_by_id.get(s.need_id)
        layer = (need.layer if need else s.layer) or "operations"
        nodes.append({
            "key": f"s{s.id}",
            "kind": "service",
            "id": s.id,
            "layer": layer if layer in LAYER_INDEX else "operations",
            "sort": _sort_key(need) + (s.name or "",),
            "name": s.display_name,
            "need": need.name if need else "",
            "need_slug": need.slug if need else "",
            "role": s.role or "",
            "status": s.status or "running",
            "status_label": STATUS_LABEL.get(s.status or "running", "Running"),
            "url": s.url or "",
            "notes": s.notes or "",
            "initials": s.initials,
            "mark": s.mark_url,
            "runbook": s.runbook_url,
            "runbook_missing": s.playbook_id is None and not (need is not None and need.in_house),
        })
    filled = {s.need_id for s in services if s.need_id}
    for n in needs:
        if n.essential and n.id not in filled:
            nodes.append({
                "key": f"n{n.id}",
                "kind": "hole",
                "id": n.id,
                "layer": n.layer if n.layer in LAYER_INDEX else "operations",
                "sort": _sort_key(n) + ("",),
                "name": n.name,
                "need": n.name,
                "need_slug": n.slug,
                "role": n.description or "",
                "status": "missing",
                "status_label": "Missing",
                "suggestions": n.suggestions,
            })

    # Columns: only the layers something sits in, in build order.
    present = sorted({n["layer"] for n in nodes}, key=lambda k: LAYER_INDEX[k])
    col_x = {key: LEFT + i * COL_W for i, key in enumerate(present)}
    rows = {key: 0 for key in present}
    for node in sorted(nodes, key=lambda n: (LAYER_INDEX[n["layer"]], n["sort"])):
        node["x"] = col_x[node["layer"]]
        node["y"] = TOP + rows[node["layer"]] * ROW_H
        rows[node["layer"]] += 1
        node.pop("sort", None)

    by_key = {n["key"]: n for n in nodes}
    service_nodes = {n["id"]: n for n in nodes if n["kind"] == "service"}

    # Edges: the template's connections between any two filled needs, then
    # this business's own, which win over a template edge on the same pair.
    edges = {}
    by_need = {}
    for s in services:
        if s.need_id:
            by_need.setdefault(s.need_id, []).append(s)
    for nl in need_links:
        for a in by_need.get(nl.from_need_id, []):
            for b in by_need.get(nl.to_need_id, []):
                pair = tuple(sorted((a.id, b.id)))
                edges[pair] = {"a": f"s{a.id}", "b": f"s{b.id}", "why": nl.why or "", "derived": True}
    for l in links:
        if l.from_service_id in service_nodes and l.to_service_id in service_nodes:
            pair = tuple(sorted((l.from_service_id, l.to_service_id)))
            edges[pair] = {"a": f"s{l.from_service_id}", "b": f"s{l.to_service_id}",
                           "why": l.why or "", "derived": False, "id": l.id}

    out_edges = []
    for pair, e in edges.items():
        a, b = by_key[e["a"]], by_key[e["b"]]
        e["path"] = _path(a, b)
        e["label"] = f"{a['name']} to {b['name']}"
        out_edges.append(e)

    width = (LEFT + len(present) * COL_W) if present else LEFT + COL_W
    height = TOP + (max(rows.values()) if rows else 1) * ROW_H + 40
    holes = [n for n in nodes if n["kind"] == "hole"]
    no_runbook = [n for n in nodes if n["kind"] == "service" and n["runbook_missing"]]
    return {
        "nodes": nodes,
        "edges": out_edges,
        "columns": [{"key": k, "label": LAYER_LABEL[k], "color": LAYER_COLOR[k], "x": col_x[k]}
                    for k in present],
        "width": width,
        "height": height,
        "counts": {"services": len(services), "holes": len(holes),
                   "no_runbook": len(no_runbook), "edges": len(out_edges)},
    }


def _path(a, b):
    """A cubic between two nodes.

    Left column to right column leaves the right side of one and enters the
    left side of the other. Two nodes in one column are joined by an arc that
    bulges to the right, so it never runs through the nodes between them.
    """
    if a["x"] == b["x"]:
        top, bottom = (a, b) if a["y"] <= b["y"] else (b, a)
        bulge = a["x"] + NODE_R + 48
        return (f"M {top['x'] + NODE_R} {top['y']} C {bulge} {top['y']}, "
                f"{bulge} {bottom['y']}, {bottom['x'] + NODE_R} {bottom['y']}")
    left, right = (a, b) if a["x"] < b["x"] else (b, a)
    x1, y1 = left["x"] + NODE_R, left["y"]
    x2, y2 = right["x"] - NODE_R, right["y"]
    dx = max(60, (x2 - x1) / 2)
    return f"M {x1} {y1} C {x1 + dx} {y1}, {x2 - dx} {y2}, {x2} {y2}"
