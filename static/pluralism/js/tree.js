(function () {
    "use strict";

    /* ── Tradition family legend mapping ── */
    const FAMILIES = [
        { label: "Early Church", color: "#c9b458" },
        { label: "Catholic", color: "#c0392b" },
        { label: "Eastern Orthodox", color: "#2471a3" },
        { label: "Oriental Orthodox", color: "#3a6fa5" },
        { label: "Lutheran / Reformed", color: "#27ae60" },
        { label: "Anglican", color: "#1e8449" },
        { label: "Anabaptist", color: "#16a085" },
        { label: "Baptist / Methodist", color: "#e67e22" },
        { label: "Pentecostal / Charismatic", color: "#9b59b6" },
        { label: "Restorationist", color: "#f39c12" },
        { label: "Heterodox / Other", color: "#7f8c8d" },
    ];

    /* ── Sizing ── */
    const WIDTH = 4000;
    const HEIGHT = 6000;
    const MARGIN = { top: 200, right: 300, bottom: 200, left: 160 };

    const svg = d3.select("#tree-svg");
    const container = svg.append("g").attr("class", "canvas");

    /* ── Zoom ── */
    let currentTransform = d3.zoomIdentity;
    const zoom = d3.zoom()
        .scaleExtent([0.15, 4])
        .on("zoom", (e) => {
            currentTransform = e.transform;
            container.attr("transform", e.transform);
            updateYearIndicator();
            updateMinimap();
            updateEraButtons();
        });
    svg.call(zoom);

    /* ── UI refs ── */
    const tooltip = d3.select("#tooltip");
    const detailPanel = d3.select("#detail-panel");
    const panelContent = d3.select("#panel-content");
    const searchInput = d3.select("#search-input");
    const searchResults = d3.select("#search-results");
    const yearIndicator = d3.select("#year-indicator");
    const minimapSvg = d3.select("#minimap-svg");

    /* ── Shared state (set during render) ── */
    let _yScale = null;
    let _root = null;

    /* ── Legend toggle (mobile) ── */
    d3.select("#legend-toggle").on("click", function () {
        const legend = d3.select("#legend");
        const isVisible = legend.classed("mobile-visible");
        legend.classed("mobile-visible", !isVisible);
        d3.select(this).classed("active", !isVisible);
    });

    /* ── Build Legend ── */
    const legendEl = d3.select("#legend");
    legendEl.append("div").attr("class", "legend-title").text("Tradition Families");
    FAMILIES.forEach((f) => {
        const item = legendEl.append("div").attr("class", "legend-item");
        item.append("div")
            .attr("class", "legend-swatch")
            .style("background", f.color);
        item.append("span").text(f.label);
    });

    /* Status indicators */
    legendEl.append("div").attr("class", "legend-title").style("margin-top", "10px").text("Status");
    const activeItem = legendEl.append("div").attr("class", "legend-item");
    activeItem.append("div").attr("class", "legend-swatch").style("background", "#999");
    activeItem.append("span").text("Active today");
    const extinctItem = legendEl.append("div").attr("class", "legend-item");
    extinctItem.append("div").attr("class", "legend-swatch legend-swatch-extinct");
    extinctItem.append("span").text("Extinct");

    /* ── Load data ── */
    d3.json("/Pluralism/api/denominations").then((data) => {
        render(data);
    });

    function render(data) {
        const lookup = new Map(data.map((d) => [d.id, d]));

        /* ── Year scale (Y axis) — oldest at bottom ── */
        const years = data.map((d) => d.founded);
        const minYear = Math.min(...years);
        const maxYear = Math.max(...years);

        const yScale = d3.scaleLinear()
            .domain([maxYear + 30, minYear - 30])
            .range([MARGIN.top, HEIGHT - MARGIN.bottom]);
        _yScale = yScale;

        /* ── Build tree hierarchy ── */
        const root = d3.stratify()
            .id((d) => d.id)
            .parentId((d) => d.parent)(data);

        _root = root;

        /* ── Assign x positions using a tree layout for spreading ── */
        const treeLayout = d3.tree()
            .size([WIDTH - MARGIN.left - MARGIN.right, HEIGHT - MARGIN.top - MARGIN.bottom])
            .separation((a, b) => (a.parent === b.parent ? 1.2 : 2));

        treeLayout(root);

        /* Remap: use tree's x for horizontal spread, yScale for vertical by year */
        root.descendants().forEach((d) => {
            d._treeX = d.x + MARGIN.left;
            d._treeY = yScale(d.data.founded);
            d.x = d._treeX;
            d.y = d._treeY;
        });

        /* ── Adherent-based radius ── */
        const maxAdherents = Math.max(...data.map((d) => d.adherents || 1));
        const radiusScale = d3.scaleSqrt()
            .domain([0, maxAdherents])
            .range([4, 38]);

        function nodeRadius(d) {
            /* Extinct nodes get a minimum 7px radius so they're clickable */
            if (d.data.extinct) return 7;
            return Math.max(4, radiusScale(d.data.adherents || 1));
        }

        /* ── Timeline ruler ── */
        const timelineTicks = [];
        for (let y = Math.ceil(minYear / 100) * 100; y <= maxYear; y += 100) {
            timelineTicks.push(y);
        }
        /* Add key years */
        [33, 1054, 1517].forEach((y) => {
            if (!timelineTicks.includes(y)) timelineTicks.push(y);
        });
        timelineTicks.sort((a, b) => a - b);

        const timelineG = container.append("g").attr("class", "timeline");

        timelineG.selectAll(".timeline-tick")
            .data(timelineTicks)
            .join("g")
            .attr("class", "timeline-tick")
            .attr("transform", (d) => `translate(0, ${yScale(d)})`)
            .each(function (d) {
                const g = d3.select(this);
                g.append("line")
                    .attr("x1", MARGIN.left - 40)
                    .attr("x2", WIDTH - MARGIN.right + 40)
                    .style("stroke-dasharray", d === 1054 || d === 1517 ? "6,3" : "2,4");
                g.append("text")
                    .attr("x", MARGIN.left - 50)
                    .attr("y", 4)
                    .attr("text-anchor", "end")
                    .text(d <= 0 ? `${Math.abs(d)} BCE` : `${d} CE`);
            });

        /* Key event labels */
        const events = [
            { year: 33, label: "Pentecost" },
            { year: 1054, label: "Great Schism" },
            { year: 1517, label: "Protestant Reformation" },
        ];
        timelineG.selectAll(".timeline-label")
            .data(events)
            .join("text")
            .attr("class", "timeline-label")
            .attr("x", MARGIN.left - 50)
            .attr("y", (d) => yScale(d.year) + 16)
            .attr("text-anchor", "end")
            .text((d) => d.label);

        /* ── Links (bezier curves) ── */
        const links = root.links();

        const linkG = container.append("g").attr("class", "links");

        const linkPaths = linkG.selectAll(".link")
            .data(links)
            .join("path")
            .attr("class", "link")
            .attr("stroke", (d) => d.target.data.color)
            .attr("d", (d) => {
                const sx = d.source.x;
                const sy = d.source.y;
                const tx = d.target.x;
                const ty = d.target.y;
                const my = (sy + ty) / 2;
                return `M${sx},${sy} C${sx},${my} ${tx},${my} ${tx},${ty}`;
            });

        /* Animate links drawing from bottom to top chronologically */
        linkPaths.each(function () {
            const path = this;
            const length = path.getTotalLength();
            d3.select(path)
                .attr("stroke-dasharray", length)
                .attr("stroke-dashoffset", length)
                .transition()
                .delay((d) => {
                    const normalizedYear = (d.target.data.founded - minYear) / (maxYear - minYear);
                    return normalizedYear * 2500 + 300;
                })
                .duration(800)
                .ease(d3.easeCubicOut)
                .attr("stroke-dashoffset", 0);
        });

        /* ── Nodes ── */
        const nodeG = container.append("g").attr("class", "nodes");

        const nodes = nodeG.selectAll(".node")
            .data(root.descendants())
            .join("g")
            .attr("class", "node")
            .attr("transform", (d) => `translate(${d.x}, ${d.y})`);

        function isExtinct(d) {
            return d.data.extinct;
        }

        const circles = nodes.append("circle")
            .attr("class", (d) => "node-circle" + (isExtinct(d) ? " extinct" : ""))
            .attr("r", 0)
            .attr("fill", (d) => isExtinct(d) ? "rgba(255,255,255,0.03)" : d.data.color)
            .attr("stroke", (d) => d.data.color)
            .attr("stroke-width", (d) => isExtinct(d) ? 2.5 : 1)
            .attr("stroke-dasharray", (d) => isExtinct(d) ? "5,3" : "none")
            .style("color", (d) => d.data.color)
            .on("mouseenter", onNodeHover)
            .on("mousemove", onNodeMove)
            .on("mouseleave", onNodeLeave)
            .on("click", onNodeClick);

        /* Animate nodes appearing chronologically */
        circles.transition()
            .delay((d) => {
                const normalizedYear = (d.data.founded - minYear) / (maxYear - minYear);
                return normalizedYear * 2500 + 500;
            })
            .duration(600)
            .ease(d3.easeBackOut.overshoot(1.5))
            .attr("r", nodeRadius);

        /* ── Labels with collision resolution and leader lines ── */
        const PAD = 4;       /* px padding between labels */
        const CHAR_W = 6.2;  /* approximate px per character at 10px font */
        const LABEL_H = 13;  /* line height */

        /* Build label rects: start each label above its node */
        const labelData = root.descendants().map((d) => {
            const r = nodeRadius(d);
            const w = d.data.name.length * CHAR_W;
            return {
                node: d,
                id: d.data.id,
                name: d.data.name,
                /* label center position */
                lx: d.x,
                ly: d.y - r - LABEL_H / 2 - 4,
                w,
                h: LABEL_H,
                /* node anchor point for leader line */
                nx: d.x,
                ny: d.y,
                r,
            };
        });

        /* Check overlap between two label rects */
        function labelsOverlap(a, b) {
            return Math.abs(a.lx - b.lx) < (a.w + b.w) / 2 + PAD &&
                   Math.abs(a.ly - b.ly) < (a.h + b.h) / 2 + PAD;
        }

        /* Max distance a label can drift from its node */
        const MAX_DRIFT = 80;

        /* Resolve collisions: iterative vertical relaxation */
        for (let pass = 0; pass < 16; pass++) {
            labelData.sort((a, b) => a.lx - b.lx);
            let moved = false;

            for (let i = 0; i < labelData.length; i++) {
                for (let j = i + 1; j < labelData.length; j++) {
                    const a = labelData[i];
                    const b = labelData[j];

                    if (b.lx - a.lx > (a.w + b.w) / 2 + PAD + 40) break;
                    if (!labelsOverlap(a, b)) continue;

                    moved = true;
                    const victim = (a.node.data.adherents || 0) < (b.node.data.adherents || 0) ? a : b;

                    /* Push down below its own node */
                    const belowY = victim.ny + victim.r + LABEL_H / 2 + 6;
                    if (victim.ly < belowY) {
                        victim.ly = belowY;
                        if (!labelsOverlap(a, b)) continue;
                    }

                    /* Keep pushing down in increments */
                    victim.ly += LABEL_H + PAD + 2;
                }
            }
            if (!moved) break;
        }

        const labelPosMap = new Map(labelData.map((l) => [l.id, l]));

        /* Draw leader lines from node edge to label edge */
        const leaderG = nodeG.append("g").attr("class", "leader-lines");
        labelData.forEach((l) => {
            const dx = l.lx - l.nx;
            const dy = l.ly - l.ny;
            const dist = Math.sqrt(dx * dx + dy * dy);
            /* Only draw if label displaced significantly */
            if (dist > l.r + LABEL_H + 12) {
                /* Start from node circle edge */
                const angle = Math.atan2(dy, dx);
                const x1 = l.nx + Math.cos(angle) * (l.r + 2);
                const y1 = l.ny + Math.sin(angle) * (l.r + 2);
                /* End at nearest label edge (horizontally centered) */
                const x2 = l.lx - Math.cos(angle) * Math.min(l.w / 2, 10);
                const y2 = l.ly - LABEL_H / 3; /* align with text baseline */
                leaderG.append("line")
                    .attr("class", "leader-line")
                    .attr("x1", x1)
                    .attr("y1", y1)
                    .attr("x2", x2)
                    .attr("y2", y2);
            }
        });

        /* Render labels at resolved positions */
        const labelNodes = container.append("g").attr("class", "label-layer");
        const labels = labelNodes.selectAll(".node-label")
            .data(root.descendants())
            .join("text")
            .attr("class", (d) => "node-label" + (d.data.extinct ? " extinct-label" : ""))
            .attr("x", (d) => {
                const l = labelPosMap.get(d.data.id);
                return l ? l.lx : d.x;
            })
            .attr("y", (d) => {
                const l = labelPosMap.get(d.data.id);
                return l ? l.ly + LABEL_H / 3 : d.y - nodeRadius(d) - 6;
            })
            .attr("text-anchor", "middle")
            .text((d) => d.data.name)
            .style("opacity", 0);

        labels.transition()
            .delay((d) => {
                const normalizedYear = (d.data.founded - minYear) / (maxYear - minYear);
                return normalizedYear * 2500 + 900;
            })
            .duration(400)
            .style("opacity", 1);

        /* ── Tooltip handlers ── */
        function onNodeHover(event, d) {
            tooltip.classed("visible", true);
            const extinct = d.data.extinct;
            tooltip.html(`
                <div class="tt-name">${d.data.name}</div>
                <div class="tt-date">${formatYear(d.data.founded)}${extinct ? ' <span class="tt-extinct">Extinct</span>' : ''}</div>
                ${d.data.founder ? `<div class="tt-founder">${d.data.founder}</div>` : ""}
            `);
        }

        function onNodeMove(event) {
            const x = event.clientX + 16;
            const y = event.clientY - 10;
            tooltip.style("left", x + "px").style("top", y + "px");
        }

        function onNodeLeave() {
            tooltip.classed("visible", false);
        }

        /* ── Click → detail panel ── */
        function onNodeClick(event, d) {
            event.stopPropagation();
            showDetailPanel(d.data);
            highlightLineage(d);
        }

        function showDetailPanel(data) {
            detailPanel.classed("hidden", false);
            panelContent.html(`
                <div class="panel-header">
                    <div class="panel-name">${data.name}</div>
                    <div class="panel-founded">${formatYear(data.founded)}${data.location ? " \u2014 " + data.location : ""}</div>
                    <div class="panel-color-bar" style="background:${data.color}"></div>
                </div>

                <div class="panel-section">
                    <div class="panel-section-title">Summary</div>
                    <p>${data.summary}</p>
                </div>

                ${data.founder ? `
                <div class="panel-stat">
                    <span class="panel-stat-label">Founder</span>
                    <span class="panel-stat-value">${data.founder}</span>
                </div>` : ""}

                ${data.adherents ? `
                <div class="panel-stat">
                    <span class="panel-stat-label">Estimated Adherents</span>
                    <span class="panel-stat-value">${formatNumber(data.adherents)}</span>
                </div>` : ""}

                <div class="panel-stat">
                    <span class="panel-stat-label">Founded</span>
                    <span class="panel-stat-value">${formatYear(data.founded)}</span>
                </div>

                <div class="panel-stat">
                    <span class="panel-stat-label">Location</span>
                    <span class="panel-stat-value">${data.location || "Unknown"}</span>
                </div>

                <div class="panel-section">
                    <div class="panel-section-title">Key Doctrines</div>
                    <ul>${(data.keyDoctrines || []).map((d) => `<li>${d}</li>`).join("")}</ul>
                </div>

                <div class="panel-section">
                    <div class="panel-section-title">Scripture Stance</div>
                    <p>${data.scriptureStance || "N/A"}</p>
                </div>

                <div class="panel-section">
                    <div class="panel-section-title">Salvation View</div>
                    <p>${data.salvationView || "N/A"}</p>
                </div>
            `);
        }

        /* Close panel */
        d3.select("#close-panel").on("click", () => {
            detailPanel.classed("hidden", true);
            clearHighlight();
        });

        svg.on("click", () => {
            detailPanel.classed("hidden", true);
            clearHighlight();
        });

        /* ── Lineage highlighting ── */
        function highlightLineage(node) {
            const ancestors = new Set();
            let current = node;
            while (current) {
                ancestors.add(current.data.id);
                current = current.parent;
            }

            /* Also highlight descendants */
            function addDescendants(n) {
                ancestors.add(n.data.id);
                if (n.children) n.children.forEach(addDescendants);
            }
            addDescendants(node);

            circles
                .classed("highlighted", (d) => ancestors.has(d.data.id))
                .classed("dimmed", (d) => !ancestors.has(d.data.id));

            labels
                .classed("highlighted", (d) => ancestors.has(d.data.id))
                .classed("dimmed", (d) => !ancestors.has(d.data.id));

            linkPaths
                .classed("highlighted", (d) =>
                    ancestors.has(d.source.data.id) && ancestors.has(d.target.data.id)
                )
                .classed("dimmed", (d) =>
                    !(ancestors.has(d.source.data.id) && ancestors.has(d.target.data.id))
                );
        }

        function clearHighlight() {
            circles.classed("highlighted", false).classed("dimmed", false);
            labels.classed("highlighted", false).classed("dimmed", false);
            linkPaths.classed("highlighted", false).classed("dimmed", false);
        }

        /* ── Search ── */
        searchInput.on("input", function () {
            const query = this.value.trim().toLowerCase();
            if (query.length < 2) {
                searchResults.classed("visible", false);
                clearHighlight();
                return;
            }

            const matches = data.filter((d) =>
                d.name.toLowerCase().includes(query) ||
                (d.founder && d.founder.toLowerCase().includes(query))
            ).slice(0, 8);

            if (matches.length === 0) {
                searchResults.classed("visible", false);
                return;
            }

            searchResults.classed("visible", true);
            searchResults.html("");

            matches.forEach((m) => {
                const item = searchResults.append("div")
                    .attr("class", "search-result-item")
                    .on("click", () => {
                        searchResults.classed("visible", false);
                        searchInput.property("value", m.name);

                        /* Find the node in the hierarchy */
                        const targetNode = root.descendants().find((d) => d.data.id === m.id);
                        if (!targetNode) return;

                        /* Pan to node */
                        const fullWidth = svg.node().clientWidth;
                        const fullHeight = svg.node().clientHeight;
                        svg.transition()
                            .duration(800)
                            .call(
                                zoom.transform,
                                d3.zoomIdentity
                                    .translate(fullWidth / 2, fullHeight / 2)
                                    .scale(1.2)
                                    .translate(-targetNode.x, -targetNode.y)
                            );

                        showDetailPanel(m);
                        highlightLineage(targetNode);
                    });

                item.html(
                    `<span class="result-name">${m.name}</span>` +
                    `<span class="result-date">${formatYear(m.founded)}</span>`
                );
            });
        });

        searchInput.on("blur", () => {
            setTimeout(() => searchResults.classed("visible", false), 200);
        });

        /* ── Era Quick-Jump ── */
        const eras = {
            early:       { year: 200,  label: "Early Church" },
            schism:      { year: 1054, label: "Great Schism" },
            reformation: { year: 1550, label: "Reformation" },
            modern:      { year: 1920, label: "Modern" },
        };

        d3.selectAll(".era-btn").on("click", function () {
            const eraKey = this.dataset.era;
            const era = eras[eraKey];
            if (!era) return;

            const targetY = yScale(era.year);
            const fullWidth = svg.node().clientWidth;
            const fullHeight = svg.node().clientHeight;
            const cx = WIDTH / 2;

            svg.transition()
                .duration(900)
                .ease(d3.easeCubicInOut)
                .call(
                    zoom.transform,
                    d3.zoomIdentity
                        .translate(fullWidth / 2, fullHeight / 2)
                        .scale(0.8)
                        .translate(-cx, -targetY)
                );
        });

        /* ── Zoom Controls ── */
        d3.select("#zoom-in").on("click", () => {
            svg.transition().duration(300).call(zoom.scaleBy, 1.5);
        });

        d3.select("#zoom-out").on("click", () => {
            svg.transition().duration(300).call(zoom.scaleBy, 0.67);
        });

        d3.select("#zoom-reset").on("click", () => {
            fitToView(800);
        });

        function fitToView(duration) {
            const bounds = container.node().getBBox();
            const fullWidth = svg.node().clientWidth;
            const fullHeight = svg.node().clientHeight;
            const scale = Math.min(
                fullWidth / (bounds.width + 100),
                fullHeight / (bounds.height + 100)
            ) * 0.85;
            const cx = bounds.x + bounds.width / 2;
            const cy = bounds.y + bounds.height / 2;
            svg.transition()
                .duration(duration)
                .call(
                    zoom.transform,
                    d3.zoomIdentity
                        .translate(fullWidth / 2, fullHeight / 2)
                        .scale(scale)
                        .translate(-cx, -cy)
                );
        }

        /* ── Minimap ── */
        const mmW = 160, mmH = 240;
        const bounds = container.node().getBBox();
        const mmScaleX = mmW / (bounds.width + 100);
        const mmScaleY = mmH / (bounds.height + 100);
        const mmScale = Math.min(mmScaleX, mmScaleY);
        const mmOffX = (mmW - bounds.width * mmScale) / 2 - bounds.x * mmScale;
        const mmOffY = (mmH - bounds.height * mmScale) / 2 - bounds.y * mmScale;

        /* Draw simplified links */
        const mmLinksG = minimapSvg.append("g")
            .attr("transform", `translate(${mmOffX},${mmOffY}) scale(${mmScale})`);

        mmLinksG.selectAll(".minimap-link")
            .data(links)
            .join("line")
            .attr("class", "minimap-link")
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);

        /* Draw dots */
        mmLinksG.selectAll(".minimap-dot")
            .data(root.descendants())
            .join("circle")
            .attr("class", "minimap-dot")
            .attr("cx", d => d.x)
            .attr("cy", d => d.y)
            .attr("r", d => Math.max(2, nodeRadius(d) * 0.4))
            .attr("fill", d => d.data.color);

        /* Viewport rectangle */
        const mmViewport = minimapSvg.append("rect")
            .attr("class", "minimap-viewport");

        /* Minimap click → pan main view */
        d3.select("#minimap").on("click", function (event) {
            const rect = this.getBoundingClientRect();
            const mx = event.clientX - rect.left;
            const my = event.clientY - rect.top;
            /* Convert minimap coords to tree coords */
            const treeX = (mx - mmOffX) / mmScale;
            const treeY = (my - mmOffY) / mmScale;
            const fullWidth = svg.node().clientWidth;
            const fullHeight = svg.node().clientHeight;

            svg.transition()
                .duration(600)
                .call(
                    zoom.transform,
                    d3.zoomIdentity
                        .translate(fullWidth / 2, fullHeight / 2)
                        .scale(currentTransform.k)
                        .translate(-treeX, -treeY)
                );
        });

        /* ── Initial view ── */
        setTimeout(() => fitToView(1200), 500);
    }

    /* ── Year Indicator ── */
    let yearIndicatorTimer = null;
    function updateYearIndicator() {
        if (!_yScale) return;
        const fullHeight = svg.node().clientHeight;
        /* Invert screen top/bottom to tree Y coords, then to years */
        const invScale = _yScale.invert;
        const topY = (0 - currentTransform.y) / currentTransform.k;
        const botY = (fullHeight - currentTransform.y) / currentTransform.k;
        const topYear = Math.round(_yScale.invert(topY));
        const botYear = Math.round(_yScale.invert(botY));
        const lo = Math.min(topYear, botYear);
        const hi = Math.max(topYear, botYear);
        yearIndicator.text(`${formatYear(lo)}  \u2013  ${formatYear(hi)}`);
        yearIndicator.classed("visible", true);

        clearTimeout(yearIndicatorTimer);
        yearIndicatorTimer = setTimeout(() => {
            yearIndicator.classed("visible", false);
        }, 2000);
    }

    /* ── Minimap viewport update ── */
    function updateMinimap() {
        if (!_root) return;
        const mmEl = document.getElementById("minimap-svg");
        if (!mmEl) return;
        const rect = minimapSvg.select(".minimap-viewport");
        if (rect.empty()) return;

        const fullWidth = svg.node().clientWidth;
        const fullHeight = svg.node().clientHeight;

        /* Get the bounds used for minimap scaling */
        const bounds = container.node().getBBox();
        const mmW = 160, mmH = 240;
        const mmScaleX = mmW / (bounds.width + 100);
        const mmScaleY = mmH / (bounds.height + 100);
        const mmScale = Math.min(mmScaleX, mmScaleY);
        const mmOffX = (mmW - bounds.width * mmScale) / 2 - bounds.x * mmScale;
        const mmOffY = (mmH - bounds.height * mmScale) / 2 - bounds.y * mmScale;

        /* Visible region in tree coords */
        const vx = (0 - currentTransform.x) / currentTransform.k;
        const vy = (0 - currentTransform.y) / currentTransform.k;
        const vw = fullWidth / currentTransform.k;
        const vh = fullHeight / currentTransform.k;

        /* Convert to minimap coords */
        rect.attr("x", vx * mmScale + mmOffX)
            .attr("y", vy * mmScale + mmOffY)
            .attr("width", vw * mmScale)
            .attr("height", vh * mmScale);
    }

    /* ── Era button active state ── */
    function updateEraButtons() {
        if (!_yScale) return;
        const fullHeight = svg.node().clientHeight;
        const centerY = (fullHeight / 2 - currentTransform.y) / currentTransform.k;
        const centerYear = Math.round(_yScale.invert(centerY));

        d3.selectAll(".era-btn").classed("active", function () {
            const era = this.dataset.era;
            if (era === "early") return centerYear < 500;
            if (era === "schism") return centerYear >= 500 && centerYear < 1400;
            if (era === "reformation") return centerYear >= 1400 && centerYear < 1800;
            if (era === "modern") return centerYear >= 1800;
            return false;
        });
    }

    /* ── Helpers ── */
    function formatYear(y) {
        if (y <= 0) return `${Math.abs(y)} BCE`;
        return `${y} CE`;
    }

    function formatNumber(n) {
        if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
        if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
        if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
        return n.toString();
    }
})();
