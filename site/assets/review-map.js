(() => {
  "use strict";
  const data = window.SATN_DATA;
  const network = data.network;
  const places = data.places;
  const state = { pinned: null, active: null };
  const routeLayers = ["low-traffic-areas", "urban-spines", "connections"];
  const warningLayers = ["gaps", "crossing-warnings"];

  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors"
        }
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }]
    },
    center: [-2.5, 51.4],
    zoom: 10
  });
  map.addControl(new maplibregl.NavigationControl());

  function value(value, fallback = "Not available") {
    return value === null || value === undefined || value === "" ? fallback : value;
  }

  function parseList(raw) {
    try { return Array.isArray(raw) ? raw : JSON.parse(raw || "[]"); }
    catch (_) { return []; }
  }

  function addDefinition(list, term, description, className = "") {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = String(description);
    if (className) dd.className = className;
    list.append(dt, dd);
  }

  function setHighlight(id) {
    state.active = id;
    document.querySelectorAll(".connection").forEach((item) => {
      item.classList.toggle("active", item.dataset.featureId === id);
      item.setAttribute("aria-pressed", String(state.pinned === item.dataset.featureId));
    });
    if (map.getLayer("connections-highlight")) {
      map.setFilter("connections-highlight", id ? ["==", ["id"], id] : ["==", ["id"], ""]);
    }
  }

  function showDetails(id) {
    const feature = network.features.find((candidate) => candidate.id === id);
    if (!feature) return;
    const properties = feature.properties;
    const panel = document.querySelector("#feature-details");
    panel.replaceChildren();
    const heading = document.createElement("h2");
    heading.id = "details-heading";
    heading.textContent = `${value(properties.from_place)} → ${value(properties.to_place)}`;
    const list = document.createElement("dl");
    addDefinition(list, "Stable ID", id);
    addDefinition(list, "Status", value(properties.status));
    addDefinition(list, "Length", properties.distance_km == null ? "Unknown" : `${properties.distance_km} km`);
    addDefinition(list, "Route role", value(properties.classification));
    addDefinition(list, "Endpoint criterion", value(properties.criterion_endpoints));
    addDefinition(list, "Continuity criterion", value(properties.criterion_continuity));
    addDefinition(list, "Two-way criterion", value(properties.criterion_bidirectional));
    addDefinition(list, "Distance criterion", value(properties.criterion_distance));
    addDefinition(list, "Rationale", value(properties.selection_reason));
    addDefinition(list, "Agent gate", value(properties.agent_outcome));
    const findings = parseList(properties.agent_findings);
    addDefinition(list, "Findings", findings.length ? findings.map((finding) => finding.message).join("; ") : "None");
    addDefinition(list, "Source identifiers", parseList(properties.source_ids).join(", ") || "None");
    panel.append(heading, list);
    setHighlight(id);
  }

  function clearTransient() {
    if (!state.pinned) {
      document.querySelector("#feature-details").innerHTML = '<h2 id="details-heading">Details</h2><p>Hover or focus a route. Click to pin its details.</p>';
      setHighlight(null);
    }
  }

  function togglePin(id) {
    state.pinned = state.pinned === id ? null : id;
    if (state.pinned) showDetails(id); else clearTransient();
    setHighlight(state.pinned || state.active);
  }

  function renderCards() {
    const list = document.querySelector("#connection-list");
    network.features
      .filter((feature) => ["connection", "gap"].includes(feature.properties.feature_type))
      .forEach((feature) => {
        const button = document.createElement("button");
        button.type = "button";
        button.id = `item-${feature.id}`;
        button.className = `connection ${feature.properties.feature_type === "gap" ? "gap" : ""}`;
        button.dataset.featureId = feature.id;
        button.setAttribute("aria-pressed", "false");
        const title = document.createElement("strong");
        title.textContent = `${value(feature.properties.from_place)} → ${value(feature.properties.to_place)}`;
        const summary = document.createElement("span");
        summary.textContent = `${value(feature.properties.distance_km, "Unknown distance")} · ${value(feature.properties.status)}`;
        button.append(title, summary);
        button.addEventListener("mouseenter", () => { if (!state.pinned) showDetails(feature.id); });
        button.addEventListener("mouseleave", clearTransient);
        button.addEventListener("focus", () => { if (!state.pinned) showDetails(feature.id); });
        button.addEventListener("click", () => togglePin(feature.id));
        list.append(button);
      });
  }

  function renderCriteria(section) {
    const heading = document.querySelector("#criteria-heading");
    heading.textContent = `${section.replaceAll("_", " ")} criteria`;
    const list = document.querySelector("#criteria-list");
    list.replaceChildren();
    Object.entries(data.criteria[section] || {}).forEach(([criterion, status]) => {
      addDefinition(list, criterion.replaceAll("_", " "), status, `criterion ${status}`);
    });
  }

  function bindControls() {
    document.querySelectorAll('input[name="section"]').forEach((input) => {
      input.addEventListener("change", () => renderCriteria(input.value));
    });
    const groups = {
      "layer-network-routes": routeLayers,
      "layer-places": ["places"],
      "layer-gaps-warnings": warningLayers,
      "layer-atm": ["atm-reference"]
    };
    Object.entries(groups).forEach(([controlId, layers]) => {
      const control = document.getElementById(controlId);
      if (!control) return;
      control.addEventListener("change", () => {
        layers.forEach((layer) => {
          if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", control.checked ? "visible" : "none");
        });
      });
    });
  }

  function extendBounds(bounds, coordinates) {
    if (typeof coordinates[0] === "number") bounds.extend(coordinates);
    else coordinates.forEach((item) => extendBounds(bounds, item));
  }

  map.on("load", () => {
    map.addSource("network", { type: "geojson", data: network });
    map.addLayer({ id: "low-traffic-areas", type: "fill", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area"], paint: { "fill-color": "#85c1e9", "fill-opacity": .3, "fill-outline-color": "#2874a6" } });
    map.addLayer({ id: "atm-reference", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "atm-reference"], paint: { "line-color": "#2980b9", "line-width": 3, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "urban-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "urban-spine"], paint: { "line-color": "#8e44ad", "line-width": 5 } });
    map.addLayer({ id: "connections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "connection"], paint: { "line-color": "#196f3d", "line-width": 6 } });
    map.addLayer({ id: "gaps", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "gap"], paint: { "circle-color": "#c0392b", "circle-radius": 8 } });
    map.addLayer({ id: "crossing-warnings", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "crossing-warning"], paint: { "circle-color": "#f39c12", "circle-radius": 7, "circle-stroke-color": "#17202a", "circle-stroke-width": 2 } });
    map.addLayer({ id: "connections-highlight", type: "line", source: "network", filter: ["==", ["id"], ""], paint: { "line-color": "#f4d03f", "line-width": 11 } });
    map.addSource("places", { type: "geojson", data: places });
    map.addLayer({ id: "places", type: "circle", source: "places", paint: { "circle-radius": 7, "circle-color": "#17202a", "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    const bounds = new maplibregl.LngLatBounds();
    [...network.features, ...places.features].forEach((feature) => extendBounds(bounds, feature.geometry.coordinates));
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 60 });
    map.on("mousemove", "connections", (event) => { if (!state.pinned) showDetails(event.features[0].id); });
    map.on("mouseleave", "connections", clearTransient);
    map.on("click", "connections", (event) => togglePin(event.features[0].id));
  });

  renderCards();
  renderCriteria("connections");
  bindControls();
})();
