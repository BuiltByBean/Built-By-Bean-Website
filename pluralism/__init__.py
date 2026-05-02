from flask import Blueprint, render_template, jsonify

from pluralism.denominations_data import DENOMINATIONS

pluralism_bp = Blueprint(
    "pluralism",
    __name__,
    url_prefix="/Pluralism",
    template_folder="../templates/pluralism",
    static_folder="../static/pluralism",
    static_url_path="/static/pluralism",
)


# Family slug → display label + colour. Keep the same 11 buckets the
# tree view used so the mental model carries over for users who saw
# the old layout. Order is the chip-stack order in the sidebar.
FAMILIES = [
    ("early-church",      "Early Church",             "#c9b458"),
    ("catholic",          "Catholic",                 "#c0392b"),
    ("eastern-orthodox",  "Eastern Orthodox",         "#2471a3"),
    ("oriental-orthodox", "Oriental Orthodox",        "#3a6fa5"),
    ("reformed",          "Lutheran / Reformed",      "#27ae60"),
    ("anglican",          "Anglican",                 "#1e8449"),
    ("anabaptist",        "Anabaptist",               "#16a085"),
    ("baptist-methodist", "Baptist / Methodist",      "#e67e22"),
    ("pentecostal",       "Pentecostal / Charismatic", "#9b59b6"),
    ("restorationist",    "Restorationist",           "#f39c12"),
    ("heterodox",         "Heterodox / Other",        "#7f8c8d"),
]

FAMILY_LABELS = {slug: label for slug, label, _ in FAMILIES}
FAMILY_COLORS = {slug: color for slug, _, color in FAMILIES}

# Direct id → family. The classifier walks the parent chain until it
# hits one of these anchors. Roots cover one family each; descendants
# inherit by walking up.
FAMILY_ANCHORS = {
    "early-church": "early-church",

    "roman-catholicism": "catholic",
    "eastern-catholic": "catholic",
    "old-catholic": "catholic",

    "eastern-orthodoxy": "eastern-orthodox",

    "nestorianism": "oriental-orthodox",
    "monophysitism": "oriental-orthodox",
    "coptic-orthodox": "oriental-orthodox",
    "ethiopian-orthodox": "oriental-orthodox",
    "armenian-apostolic": "oriental-orthodox",
    "syriac-orthodox": "oriental-orthodox",

    "lutheranism": "reformed",
    "calvinism": "reformed",
    "dutch-reformed": "reformed",
    "waldensians": "reformed",
    "moravian": "reformed",
    "puritanism": "reformed",
    "congregationalism": "reformed",

    "anglicanism": "anglican",

    "anabaptism": "anabaptist",
    "quakers": "anabaptist",
    "plymouth-brethren": "anabaptist",

    "baptists": "baptist-methodist",
    "methodism": "baptist-methodist",
    "salvation-army": "baptist-methodist",
    "cma": "baptist-methodist",
    "efca": "baptist-methodist",
    "non-denominational": "baptist-methodist",

    "pentecostalism": "pentecostal",
    "charismatic-movement": "pentecostal",
    "word-of-faith": "pentecostal",
    "vineyard": "pentecostal",
    "ihop": "pentecostal",
    "nar": "pentecostal",

    "restoration-movement": "restorationist",
    "adventism": "restorationist",

    "marcionism": "heterodox",
    "montanism": "heterodox",
    "donatism": "heterodox",
    "arianism": "heterodox",
    "mormonism": "heterodox",
    "jehovahs-witnesses": "heterodox",
    "christian-science": "heterodox",
    "unity-church": "heterodox",
    "progressive-christianity": "heterodox",
    "unitarian-universalism": "heterodox",
    "branch-davidians": "heterodox",
}


def _build_graph():
    by_id = {d["id"]: d for d in DENOMINATIONS}

    def family_for(node_id):
        # Walk parent chain until we hit an anchor. Cap iterations so a
        # data error (cycle, dangling parent) can't loop forever.
        seen = set()
        cur = node_id
        for _ in range(64):
            if cur in FAMILY_ANCHORS:
                return FAMILY_ANCHORS[cur]
            if cur in seen:
                break
            seen.add(cur)
            parent = (by_id.get(cur) or {}).get("parent")
            if not parent:
                break
            cur = parent
        return "heterodox"

    # Pre-compute degree (in + out) so node sizing in the canvas can use
    # sqrt-degree without re-walking edges every frame.
    degree = {d["id"]: 0 for d in DENOMINATIONS}
    edges = []
    for d in DENOMINATIONS:
        parent = d.get("parent")
        if parent and parent in by_id:
            edges.append({"source": parent, "target": d["id"], "kind": "descends"})
            degree[parent] = degree.get(parent, 0) + 1
            degree[d["id"]] = degree.get(d["id"], 0) + 1

    nodes = []
    family_counts = {slug: 0 for slug, _, _ in FAMILIES}
    for d in DENOMINATIONS:
        fam = family_for(d["id"])
        family_counts[fam] = family_counts.get(fam, 0) + 1
        nodes.append({
            "id": d["id"],
            "label": d["name"],
            "name": d["name"],
            "kind": fam,
            "degree": degree.get(d["id"], 0),
            "founded": d.get("founded"),
            "founder": d.get("founder"),
            "location": d.get("location"),
            "adherents": d.get("adherents"),
            "extinct": bool(d.get("extinct")),
            "summary": d.get("summary"),
            "keyDoctrines": d.get("keyDoctrines") or [],
            "scriptureStance": d.get("scriptureStance"),
            "salvationView": d.get("salvationView"),
            "parent": d.get("parent"),
        })

    return {
        "ok": True,
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "family_counts": family_counts,
            "families": [
                {"slug": s, "label": l, "color": c} for s, l, c in FAMILIES
            ],
        },
    }


@pluralism_bp.route("/")
def index():
    return render_template("base.html")


@pluralism_bp.route("/api/denominations")
def get_denominations():
    return jsonify(DENOMINATIONS)


@pluralism_bp.route("/api/graph")
def get_graph():
    return jsonify(_build_graph())
