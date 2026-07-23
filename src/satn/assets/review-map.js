(async () => {
  "use strict";
  const data = window.SATN_DATA;
  if (!data.network && data.network_url) {
    const response = await fetch(data.network_url);
    if (!response.ok) throw new Error(`Network evidence failed to load (${response.status}).`);
    data.network = await response.json();
  }
  const network = data.network;
  const places = data.places;
  const state = { pinned: null, active: null, inspectionPath: [] };
  const gradientPathTypes = new Set([
    "strategic-spine",
    "spine-access-connection",
    "school-access-connection",
    "branch-meeting-connection",
    "urban-spine"
  ]);
  const warningLayers = ["gaps", "crossing-warnings"];
  const evidenceLayers = ["strategic-spines", "access-obligations", "school-access-obligations", "school-access-gaps", "school-street-assessments", "gradient-sections", "topography-unavailable", "a-road-spines", "ncn-route-evidence", "ncn-link-evidence", "urban-spines", "urban-classification-unknowns", "low-traffic-areas", "low-traffic-area-outlines", "low-traffic-area-portals", "schools", "retail-centres", "healthcare", "atm-reference"];

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
      layers: [{
        id: "osm",
        type: "raster",
        source: "osm",
        paint: {
          "raster-opacity": .72,
          "raster-saturation": -.65,
          "raster-contrast": -.08,
          "raster-brightness-max": .94
        }
      }]
    },
    center: [-2.5, 51.4],
    zoom: 10
  });
  window.SATN_REVIEW_MAP = map;
  map.addControl(new maplibregl.NavigationControl());
  let terrainTimeout = null;
  let topographyLoaded = !data.topography_url;

  async function ensureTopographyLoaded() {
    if (topographyLoaded || !data.topography_url) return;
    const response = await fetch(data.topography_url);
    if (!response.ok) throw new Error(`Topography evidence failed to load (${response.status}).`);
    const collection = await response.json();
    map.getSource("topography")?.setData(collection);
    network.features.push(
      ...collection.features.filter((feature) => feature.properties.feature_type === "gradient-section")
    );
    topographyLoaded = true;
    renderLinearEvidence();
  }

  function restoreTwoDimensionalMap(reason = "") {
    if (terrainTimeout) window.clearTimeout(terrainTimeout);
    terrainTimeout = null;
    const control = document.querySelector("#terrain-mode");
    if (control) control.checked = false;
    try { map.setTerrain(null); } catch (_) { /* terrain was never available */ }
    map.easeTo({ pitch: 0, duration: 500 });
    const status = document.querySelector("#terrain-status");
    if (status) {
      status.textContent = reason
        ? `3D unavailable; restored 2D map. ${reason}`
        : "2D map · analytical default";
    }
  }

  map.on("error", (event) => {
    if (event.sourceId === "mapterhorn-dem" && document.querySelector("#terrain-mode")?.checked) {
      restoreTwoDimensionalMap("Terrain provider did not respond.");
    }
  });
  map.on("sourcedata", (event) => {
    if (event.sourceId === "mapterhorn-dem" && event.isSourceLoaded && terrainTimeout) {
      window.clearTimeout(terrainTimeout);
      terrainTimeout = null;
    }
  });

  function value(value, fallback = "Not available") {
    return value === null || value === undefined || value === "" ? fallback : value;
  }

  function parseList(raw) {
    try { return Array.isArray(raw) ? raw : JSON.parse(raw || "[]"); }
    catch (_) { return []; }
  }

  function profileFor(feature) {
    const profileId = feature?.properties?.topography_profile_id;
    return network.features.find((candidate) =>
      candidate.properties.feature_type === "topography-profile" &&
      candidate.properties.profile_id === profileId
    );
  }

  function eligibleForGradientPath(feature) {
    return Boolean(
      feature &&
      gradientPathTypes.has(feature.properties.feature_type) &&
      ["LineString", "MultiLineString"].includes(feature.geometry?.type) &&
      feature.properties.topography_profile_id
    );
  }

  function lineEndpoints(feature) {
    const coordinates = feature.geometry.coordinates;
    if (feature.geometry.type === "LineString") {
      return [coordinates[0], coordinates[coordinates.length - 1]];
    }
    const first = coordinates[0];
    const last = coordinates[coordinates.length - 1];
    return [first[0], last[last.length - 1]];
  }

  function distanceMetres(left, right) {
    const latitude = (left[1] + right[1]) * Math.PI / 360;
    const dx = (right[0] - left[0]) * 111320 * Math.cos(latitude);
    const dy = (right[1] - left[1]) * 110540;
    return Math.hypot(dx, dy);
  }

  function junctionKey(coordinate) {
    return `${Number(coordinate[0]).toFixed(5)},${Number(coordinate[1]).toFixed(5)}`;
  }

  function orientedEndpoints(item) {
    const endpoints = lineEndpoints(item.feature);
    return item.reversed ? [endpoints[1], endpoints[0]] : endpoints;
  }

  function updateGradientCandidate() {
    const candidate = network.features.find((feature) => feature.id === state.pinned);
    const message = document.querySelector("#gradient-path-candidate");
    const start = document.querySelector("#gradient-path-start");
    const append = document.querySelector("#gradient-path-append");
    if (!eligibleForGradientPath(candidate)) {
      message.textContent = state.pinned
        ? "Pinned feature is not an eligible analytical edge."
        : "Pin an eligible Published Feature, then start or append it.";
      start.disabled = true;
      append.disabled = true;
      return;
    }
    message.textContent = `${value(candidate.properties.name, candidate.properties.feature_type.replaceAll("-", " "))} · ${candidate.id}`;
    start.disabled = false;
    append.disabled = state.inspectionPath.length === 0;
  }

  function setInspectionPath(features) {
    state.inspectionPath = features;
    const selectedIds = features.map((item) => item.feature.id);
    const source = map.getSource("inspection-path");
    if (source) {
      source.setData({
        type: "FeatureCollection",
        features: features.map((item, index) => {
          const feature = structuredClone(item.feature);
          if (item.reversed) {
            if (feature.geometry.type === "LineString") feature.geometry.coordinates.reverse();
            else {
              feature.geometry.coordinates.reverse();
              feature.geometry.coordinates.forEach((line) => line.reverse());
            }
          }
          feature.properties = {
            ...feature.properties,
            inspection_order: index + 1,
            inspection_direction: item.reversed ? "reverse" : "forward"
          };
          return feature;
        })
      });
    }
    document.querySelector("#gradient-path-status").textContent = selectedIds.length
      ? `${selectedIds.length} edge${selectedIds.length === 1 ? "" : "s"} selected.`
      : "No path selected.";
    renderLinearEvidence();
    updateGradientCandidate();
  }

  function startPinnedPath() {
    const feature = network.features.find((candidate) => candidate.id === state.pinned);
    if (eligibleForGradientPath(feature)) setInspectionPath([{ feature, reversed: false }]);
  }

  function appendPinnedPath() {
    const feature = network.features.find((candidate) => candidate.id === state.pinned);
    if (!eligibleForGradientPath(feature) || !state.inspectionPath.length) return;
    if (state.inspectionPath.some((item) => item.feature.id === feature.id)) {
      document.querySelector("#gradient-path-status").textContent = "That edge is already in the path.";
      return;
    }
    const activeEnd = orientedEndpoints(state.inspectionPath.at(-1))[1];
    const [start, end] = lineEndpoints(feature);
    const activeJunction = junctionKey(activeEnd);
    const startGap = distanceMetres(activeEnd, start);
    const endGap = distanceMetres(activeEnd, end);
    const gap = Math.min(startGap, endGap);
    const reversed = junctionKey(end) === activeJunction;
    const joinsAtStart = junctionKey(start) === activeJunction;
    if (!reversed && !joinsAtStart) {
      document.querySelector("#gradient-path-status").textContent =
        `Edge is ${gap.toFixed(0)} m from the active endpoint but does not share its junction.`;
      return;
    }
    const farEnd = reversed ? start : end;
    const usedJunctions = new Set(
      state.inspectionPath.flatMap((item) => orientedEndpoints(item).map(junctionKey))
    );
    if (usedJunctions.has(junctionKey(farEnd))) {
      document.querySelector("#gradient-path-status").textContent =
        "That edge would revisit a path junction and form a cycle or branch.";
      return;
    }
    setInspectionPath([
      ...state.inspectionPath,
      { feature, reversed }
    ]);
  }

  function evidenceCell(track, item, totalDistance, offset, segmentIndex, segment) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = `track-cell ${item.gradient_band || "unavailable"}`;
    const length = Math.max(0.001, item.end_distance_m - item.start_distance_m);
    cell.style.flexBasis = `${length / totalDistance * 100}%`;
    const hasValue = item.status !== "unavailable" && Number.isFinite(Number(item.forward_gradient_pct));
    cell.title = hasValue
      ? `${(offset + item.start_distance_m).toFixed(0)}–${(offset + item.end_distance_m).toFixed(0)} m · ${item.forward_gradient_pct}%`
      : "Micro-gradient evidence unavailable";
    cell.textContent = hasValue ? `${item.forward_gradient_pct}%` : "—";
    cell.dataset.segmentIndex = String(segmentIndex);
    cell.dataset.featureId = segment?.feature.id || "";
    const profileId = profileFor(segment?.feature)?.properties?.profile_id;
    const originalStart = segment?.reversed
      ? segment.distance - Number(item.end_distance_m)
      : Number(item.start_distance_m);
    const originalEnd = segment?.reversed
      ? segment.distance - Number(item.start_distance_m)
      : Number(item.end_distance_m);
    const sectionIds = network.features
      .filter((feature) =>
        feature.properties.feature_type === "gradient-section" &&
        feature.properties.profile_id === profileId &&
        Number(feature.properties.start_distance_m) < originalEnd &&
        Number(feature.properties.end_distance_m) > originalStart
      )
      .map((feature) => feature.id);
    cell.dataset.gradientSectionIds = sectionIds.join(" ");
    const enter = () => {
      cell.classList.add("hovered");
      setHighlight(sectionIds[0] || segment?.feature.id);
    };
    const leave = () => {
      cell.classList.remove("hovered");
      setHighlight(state.pinned);
    };
    cell.addEventListener("mouseenter", enter);
    cell.addEventListener("focus", enter);
    cell.addEventListener("mouseleave", leave);
    cell.addEventListener("blur", leave);
    track.append(cell);
  }

  function orientedIntervals(segment, windowMetres) {
    return segment.intervals
      .filter((item) => Number(item.window_m) === windowMetres)
      .map((raw) => {
        const item = { ...raw };
        if (segment.reversed) {
          const originalStart = Number(item.start_distance_m);
          item.start_distance_m = segment.distance - Number(item.end_distance_m);
          item.end_distance_m = segment.distance - originalStart;
          item.forward_gradient_pct = -Number(item.forward_gradient_pct);
          item.uphill_direction = item.uphill_direction === "forward"
            ? "reverse"
            : item.uphill_direction === "reverse" ? "forward" : "level";
        }
        return item;
      })
      .sort((left, right) => left.start_distance_m - right.start_distance_m);
  }

  function gradientTrack(segments, totalDistance, windowMetres) {
    const row = document.createElement("div");
    row.className = "evidence-track";
    const label = document.createElement("div");
    label.className = "track-label";
    label.textContent = `Gradient · ${windowMetres} m`;
    const cells = document.createElement("div");
    cells.className = "track-cells";
    let offset = 0;
    segments.forEach((segment, segmentIndex) => {
      const intervals = orientedIntervals(segment, windowMetres);
      if (!intervals.length) {
        evidenceCell(cells, {
          start_distance_m: 0,
          end_distance_m: segment.distance,
          status: "unavailable",
          gradient_band: "unavailable"
        }, totalDistance, offset, segmentIndex, segment);
      } else {
        intervals.forEach((item) => {
          evidenceCell(cells, item, totalDistance, offset, segmentIndex, segment);
        });
      }
      offset += segment.distance;
    });
    row.append(label, cells);
    return row;
  }

  function renderLinearEvidence() {
    const chart = document.querySelector("#linear-evidence-chart");
    const summary = document.querySelector("#route-summary");
    chart.replaceChildren();
    if (!state.inspectionPath.length) {
      chart.innerHTML = '<p class="empty-evidence">No Gradient Inspection Path selected.</p>';
      summary.textContent = "Build a continuous Gradient Inspection Path to compare distance-aligned evidence.";
      return;
    }
    const segments = state.inspectionPath.map((item) => {
      const profile = profileFor(item.feature);
      const distance = Number(profile?.properties?.distance_m || item.feature.properties.topography_distance_m || 0);
      const capability = profile ? parseObject(profile.properties.micro_gradient_capability) : {};
      const intervals = profile ? parseList(profile.properties.micro_gradient_intervals) : [];
      return { ...item, profile, distance, capability, intervals };
    });
    const totalDistance = Math.max(segments.reduce((sum, item) => sum + item.distance, 0), 1);
    const measurementAvailable = segments.every((item) =>
      item.profile?.properties?.evidence_status === "available" &&
      item.capability.status !== "unavailable"
    );
    const ascent = measurementAvailable
      ? segments.reduce((sum, item) => sum + Number(
        item.reversed ? item.profile.properties.reverse_ascent_m : item.profile.properties.forward_ascent_m
      ), 0)
      : null;
    const descent = measurementAvailable
      ? segments.reduce((sum, item) => sum + Number(
        item.reversed ? item.profile.properties.reverse_descent_m : item.profile.properties.forward_descent_m
      ), 0)
      : null;
    const steepestValues = segments
      .map((item) => item.profile?.properties?.steepest_sustained_gradient_pct)
      .filter((item) => item !== null && item !== undefined && Number.isFinite(Number(item)))
      .map(Number);
    const steepest = measurementAvailable && steepestValues.length
      ? Math.max(...steepestValues)
      : null;
    const evidenceStates = [...new Set(segments.map((item) =>
      item.capability.status === "available"
        ? item.capability.evidence_quality_status || "available"
        : item.capability.status || "unavailable"
    ))];
    summary.textContent =
      `${segments.length} edge${segments.length === 1 ? "" : "s"} · ${(totalDistance / 1000).toFixed(2)} km · ` +
      `↑ ${ascent === null ? "unavailable" : `${ascent.toFixed(1)} m`} · ` +
      `↓ ${descent === null ? "unavailable" : `${descent.toFixed(1)} m`} · ` +
      `steepest sustained ${steepest === null ? "unavailable" : `${steepest.toFixed(1)}%`} · ` +
      `evidence ${evidenceStates.join(", ")} · shared distance axis`;
    const rationale = document.createElement("p");
    rationale.className = "evidence-rationale";
    rationale.textContent = [...new Set(segments.map((item) =>
      item.capability.rationale || item.profile?.properties?.evidence_rationale
    ).filter(Boolean))].join(" ");
    const axis = document.createElement("div");
    axis.className = "evidence-axis";

    const boundaryRow = document.createElement("div");
    boundaryRow.className = "evidence-track feature-boundaries";
    const boundaryLabel = document.createElement("div");
    boundaryLabel.className = "track-label";
    boundaryLabel.textContent = "Path order";
    const boundaryCells = document.createElement("div");
    boundaryCells.className = "track-cells";
    segments.forEach((segment, index) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "track-cell boundary";
      cell.style.flexBasis = `${segment.distance / totalDistance * 100}%`;
      cell.textContent = `${index + 1} ${segment.reversed ? "←" : "→"}`;
      cell.title = `${segment.feature.id} · ${segment.distance.toFixed(0)} m`;
      cell.dataset.featureId = segment.feature.id;
      cell.addEventListener("mouseenter", () => setHighlight(segment.feature.id));
      cell.addEventListener("focus", () => setHighlight(segment.feature.id));
      cell.addEventListener("mouseleave", () => setHighlight(state.pinned));
      cell.addEventListener("blur", () => setHighlight(state.pinned));
      cell.addEventListener("click", () => togglePin(segment.feature.id));
      boundaryCells.append(cell);
    });
    boundaryRow.append(boundaryLabel, boundaryCells);

    const roadRow = document.createElement("div");
    roadRow.className = "evidence-track";
    const roadLabel = document.createElement("div");
    roadLabel.className = "track-label";
    roadLabel.textContent = "Road type";
    const roadCells = document.createElement("div");
    roadCells.className = "track-cells";
    segments.forEach((segment, index) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "track-cell road";
      cell.style.flexBasis = `${segment.distance / totalDistance * 100}%`;
      cell.textContent = value(
        segment.feature.properties.official_classification,
        segment.feature.properties.spine_kind || segment.feature.properties.feature_type.replaceAll("-", " ")
      );
      cell.title = `${segment.feature.id} · future engineering evidence track`;
      cell.addEventListener("click", () => togglePin(segment.feature.id));
      cell.addEventListener("mouseenter", () => setHighlight(segment.feature.id));
      cell.addEventListener("focus", () => setHighlight(segment.feature.id));
      cell.addEventListener("mouseleave", () => setHighlight(state.pinned));
      cell.addEventListener("blur", () => setHighlight(state.pinned));
      cell.dataset.segmentIndex = String(index);
      cell.dataset.featureId = segment.feature.id;
      roadCells.append(cell);
    });
    roadRow.append(roadLabel, roadCells);

    const distanceAxis = document.createElement("div");
    distanceAxis.className = "distance-axis";
    distanceAxis.innerHTML = `<span>0 m</span><span>${Math.round(totalDistance / 2)} m</span><span>${Math.round(totalDistance)} m</span>`;
    axis.append(
      boundaryRow,
      gradientTrack(segments, totalDistance, 50),
      gradientTrack(segments, totalDistance, 20),
      roadRow,
      distanceAxis
    );
    chart.append(rationale, axis);
  }

  function parseObject(raw) {
    try { return raw && typeof raw === "object" ? raw : JSON.parse(raw || "{}"); }
    catch (_) { return {}; }
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
    if (map.getLayer("gradient-section-highlight")) {
      map.setFilter("gradient-section-highlight", id ? ["==", ["id"], id] : ["==", ["id"], ""]);
    }
    document.querySelectorAll(".track-cell[data-feature-id]").forEach((cell) => {
      cell.classList.toggle(
        "hovered",
        Boolean(id) && (
          cell.dataset.featureId === String(id) ||
          cell.dataset.gradientSectionIds?.split(" ").includes(String(id))
        )
      );
    });
  }

  function addTopographyDetails(list, properties) {
    const profileId = properties.topography_profile_id || properties.profile_id;
    if (!profileId) return;
    addDefinition(list, "Topography Profile", profileId);
    addDefinition(list, "Elevation Evidence", value(properties.topography_evidence_status, properties.evidence_status));
    addDefinition(list, "Elevation rationale", value(properties.topography_evidence_rationale, properties.evidence_rationale));
    addDefinition(list, "Measured distance", `${value(properties.topography_distance_m, properties.distance_m)} m`);
    addDefinition(list, "Forward cumulative ascent", `${value(properties.forward_ascent_m)} m`);
    addDefinition(list, "Forward cumulative descent", `${value(properties.forward_descent_m)} m`);
    addDefinition(list, "Reverse cumulative ascent", `${value(properties.reverse_ascent_m)} m`);
    addDefinition(list, "Reverse cumulative descent", `${value(properties.reverse_descent_m)} m`);
    addDefinition(list, "Steepest sustained gradient", `${value(properties.steepest_sustained_gradient_pct)}%`);
    addDefinition(list, "Sustained gradient rationale", value(properties.steepest_sustained_gradient_rationale));
    addDefinition(list, "Gradient Sections", parseList(properties.gradient_section_ids).join(", ") || "None");
  }

  function showDetails(id) {
    const feature = network.features.find((candidate) => candidate.id === id);
    if (!feature) return;
    const properties = feature.properties;
    const panel = document.querySelector("#feature-details");
    panel.replaceChildren();
    const heading = document.createElement("h2");
    heading.id = "details-heading";
    const isConnection = ["gap", "spine-access-connection", "school-access-connection", "school-access-gap", "branch-meeting-connection", "cross-spine-connector"].includes(properties.feature_type);
    heading.textContent = isConnection
      ? `${value(properties.from_place_name, properties.school_name || properties.place_name || properties.community_name || properties.from_root_spine_name || properties.from_place)} → ${value(properties.to_place_name, properties.parent_target_name || properties.spine_name || properties.to_root_spine_name || properties.to_place)}`
      : value(properties.name, properties.school_name || properties.feature_type.replaceAll("-", " "));
    const list = document.createElement("dl");
    addDefinition(list, "Stable ID", id);
    addDefinition(list, "Layer", properties.feature_type.replaceAll("-", " "));
    if (!isConnection) {
      if (properties.feature_type === "gradient-section") {
        addDefinition(list, "Gradient band", value(properties.gradient_band));
        addDefinition(list, "Length", `${value(properties.length_m)} m`);
        addDefinition(list, "Forward gradient", `${value(properties.forward_gradient_pct)}%`);
        addDefinition(list, "Uphill direction", value(properties.uphill_direction));
        addDefinition(list, "Sustained", value(properties.sustained));
        addDefinition(list, "Sustained-window rationale", value(properties.sustained_rationale));
        addDefinition(list, "Topography Profile", value(properties.profile_id));
        addDefinition(list, "Generated edge", `${value(properties.edge_type)} · ${value(properties.edge_id)}`);
        addDefinition(list, "Elevation Evidence", parseList(properties.elevation_evidence_ids).join(", ") || "None");
        panel.append(heading, list);
        setHighlight(id);
        return;
      }
      addDefinition(list, "Category", value(properties.category));
      addDefinition(list, "Network role", value(properties.network_role));
      addDefinition(list, "Intervention assumption", value(properties.intervention_assumption));
      addDefinition(list, "Design status", value(properties.design_status));
      addDefinition(list, "Mapped features", value(properties.feature_count, 1));
      addDefinition(list, "Source identifiers", value(properties.source_id));
      if (properties.feature_type === "low-traffic-area") {
        addDefinition(list, "Candidate status", value(properties.status));
        addDefinition(list, "Intervention need", value(properties.intervention_need));
        addDefinition(list, "Boundary identifiers", parseList(properties.boundary_ids).join(", ") || "None");
        addDefinition(list, "Named portals", value(properties.portal_count, 0));
        addDefinition(list, "Geometry meaning", value(properties.permeability_representation));
      }
      if (properties.feature_type === "low-traffic-area-portal") {
        addDefinition(list, "Candidate area", value(properties.area_id));
        addDefinition(list, "Circulation Boundary", value(properties.boundary_name));
        addDefinition(list, "Boundary kind", value(properties.boundary_kind));
      }
      if (["urban-spine", "urban-classification-unknown"].includes(properties.feature_type)) {
        addDefinition(list, "Official classification", value(properties.official_classification));
        addDefinition(list, "Classification status", value(properties.classification_status));
        addDefinition(list, "Effective date", value(properties.effective_date));
        addDefinition(list, "Licence", value(properties.licence));
        addDefinition(list, "Content fingerprint", value(properties.content_fingerprint));
      }
      if (["school", "school-access-obligation"].includes(properties.feature_type)) {
        addDefinition(list, "School kind", value(properties.school_kind, properties.category));
        addDefinition(list, "School access point", value(properties.access_point_status));
        addDefinition(list, "Access point source identifier", value(properties.access_point_source_id));
        addDefinition(list, "Access rationale", value(properties.access_point_rationale));
        addDefinition(list, "Service status", value(properties.service_status));
        addDefinition(list, "Service rationale", value(properties.service_rationale));
        if (properties.feature_type === "school-access-obligation") {
          addDefinition(list, "Network scope", value(properties.network_scope));
          addDefinition(list, "Continuity criterion", value(properties.criterion_continuity));
          addDefinition(list, "Candidate area", value(properties.low_traffic_area_name, properties.low_traffic_area_id));
          addDefinition(list, "Main-road portal", value(properties.portal_name, properties.portal_id));
          addDefinition(list, "Fabric source identifiers", parseList(properties.fabric_source_ids).join(", ") || "None");
          addDefinition(list, "Supporting evidence", value(properties.supporting_evidence));
          addDefinition(list, "Finding", value(properties.finding, "None"));
          addDefinition(list, "Geometry meaning", value(properties.geometry_semantics));
        }
      }
      if (properties.feature_type === "access-obligation") {
        addDefinition(list, "Service status", value(properties.service_status));
        addDefinition(list, "Service rationale", value(properties.service_rationale));
        addDefinition(list, "Network scope", value(properties.network_scope));
        addDefinition(list, "Continuity criterion", value(properties.criterion_continuity));
        addDefinition(list, "Candidate area", value(properties.low_traffic_area_name, properties.low_traffic_area_id));
        addDefinition(list, "Main-road portal", value(properties.portal_name, properties.portal_id));
        addDefinition(list, "Urban spine", value(properties.urban_spine_id));
        addDefinition(list, "Fabric source identifiers", parseList(properties.fabric_source_ids).join(", ") || "None");
        addDefinition(list, "Supporting evidence", value(properties.supporting_evidence));
        addDefinition(list, "Finding", value(properties.finding, "None"));
        addDefinition(list, "Geometry meaning", value(properties.geometry_semantics));
      }
      if (properties.feature_type === "school-street-assessment") {
        addDefinition(list, "Assessment", `${value(properties.assessment_status)} — ${value(properties.assessment_label)}`);
        addDefinition(list, "Rationale", value(properties.rationale));
        addDefinition(list, "Qualification", value(properties.qualification));
        addDefinition(list, "Entrance evidence", value(properties.access_point_status));
        addDefinition(list, "Adjoining road", value(properties.adjoining_road_classification));
        addDefinition(list, "Bus access", value(properties.bus_access));
        addDefinition(list, "Essential access", value(properties.essential_access));
        addDefinition(list, "Alternative through route", value(properties.alternative_through_route));
        addDefinition(list, "Displacement risk", value(properties.displacement_risk));
        addDefinition(list, "Missing evidence", parseList(properties.missing_evidence).join(", ") || "None");
        addDefinition(list, "Source identifiers", parseList(properties.source_ids).join(", ") || "None");
      }
      addTopographyDetails(list, properties);
      panel.append(heading, list);
      setHighlight(null);
      return;
    }
    addDefinition(list, "Status", value(properties.status));
    addDefinition(list, "Length", properties.distance_km == null ? "Unknown" : `${properties.distance_km} km`);
    if (properties.feature_type === "spine-access-connection") {
      addDefinition(list, "Community road association", properties.community_attachment_distance_m == null ? "Unknown" : `${properties.community_attachment_distance_m} m`);
      addDefinition(list, "Community road attachment", value(properties.community_attachment_point));
    }
    addDefinition(list, "Route role", value(properties.classification, properties.network_role));
    addDefinition(list, "Indicative intervention", value(properties.intervention_archetype));
    addDefinition(list, "Geometry meaning", value(properties.geometry_semantics));
    addDefinition(list, "Endpoint criterion", value(properties.criterion_endpoints));
    addDefinition(list, "Continuity criterion", value(properties.criterion_continuity));
    addDefinition(list, "Two-way criterion", value(properties.criterion_bidirectional));
    addDefinition(list, "Distance criterion", value(properties.criterion_distance));
    addDefinition(list, "Rationale", value(properties.selection_reason));
    addDefinition(list, "Agent gate", value(properties.agent_outcome));
    addDefinition(list, "Decision request", value(properties.agent_decision_request_id));
    addDefinition(list, "Selected choice", value(properties.agent_decision_choice_id));
    addDefinition(list, "Mapped action", value(properties.agent_decision_action));
    addDefinition(list, "Responder mode", value(properties.agent_decision_responder_mode));
    addDefinition(list, "Topography comparison", value(properties.topography_comparison_status, "not evaluated"));
    addDefinition(list, "Topography triggered", value(properties.topography_alternative_trigger, false));
    addDefinition(list, "Topography original role", value(properties.topography_original_role));
    addDefinition(list, "Topography selected role", value(properties.topography_selected_role));
    addDefinition(list, "Topography comparison rationale", value(properties.topography_comparison_rationale));
    addTopographyDetails(list, properties);
    if (["school-access-connection", "school-access-gap"].includes(properties.feature_type)) {
      addDefinition(list, "School kind", value(properties.school_kind));
      addDefinition(list, "School access point", value(properties.access_point_status));
      addDefinition(list, "Access rationale", value(properties.access_point_rationale));
    }
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

  function showPlaceDetails(feature) {
    if (state.pinned) return;
    const properties = feature.properties;
    const panel = document.querySelector("#feature-details");
    panel.replaceChildren();
    const heading = document.createElement("h2");
    heading.id = "details-heading";
    heading.textContent = value(properties.name, "Unnamed Network Place");
    const list = document.createElement("dl");
    addDefinition(list, "Stable ID", value(properties.place_id));
    addDefinition(list, "Place role", value(properties.kind));
    addDefinition(list, "OSM place class", value(properties.place_class));
    addDefinition(list, "Source identifier", value(properties.source_id));
    panel.append(heading, list);
  }

  function togglePin(id) {
    state.pinned = state.pinned === id ? null : id;
    if (state.pinned) showDetails(id); else clearTransient();
    setHighlight(state.pinned || state.active);
    updateGradientCandidate();
  }

  function renderCards() {
    const list = document.querySelector("#connection-list");
    list.replaceChildren();
    network.features
      .filter((feature) =>
        eligibleForGradientPath(feature) ||
        feature.properties.feature_type === "cross-spine-connector"
      )
      .forEach((feature) => {
        const button = document.createElement("button");
        button.type = "button";
        button.id = `item-${feature.id}`;
        const retainedTopography = ["original-retained-no-easier-option", "strategic-spine-retained"].includes(feature.properties.topography_comparison_status);
        button.className = `connection ${feature.properties.feature_type === "gap" ? "gap" : ""} ${retainedTopography ? "retained-topography" : ""}`;
        button.dataset.featureId = feature.id;
        button.dataset.featureType = feature.properties.feature_type;
        button.setAttribute("aria-pressed", "false");
        const title = document.createElement("strong");
        const isSchoolObligation = feature.properties.feature_type === "school-access-obligation";
        const isSchoolStreet = feature.properties.feature_type === "school-street-assessment";
        const isAreaEvidence = ["low-traffic-area", "low-traffic-area-portal"].includes(feature.properties.feature_type);
        const isTopographyProfile = feature.properties.feature_type === "topography-profile";
        const isGradientSection = feature.properties.feature_type === "gradient-section";
        const isNamedNetworkEvidence = ["strategic-spine", "access-obligation", "a-road-spine", "ncn-route", "ncn-link", "urban-spine", "urban-classification-unknown", "crossing-warning", "school", "retail-centre", "healthcare", "atm-reference"].includes(feature.properties.feature_type);
        title.textContent = isNamedNetworkEvidence
          ? value(feature.properties.name, feature.properties.school_name || feature.properties.place_name || feature.properties.community_name || feature.properties.feature_type.replaceAll("-", " "))
          : isAreaEvidence
          ? value(feature.properties.name, "Unnamed Candidate Low-Traffic Area evidence")
          : isSchoolStreet
          ? value(feature.properties.school_name, "Unnamed School Street Candidate Assessment")
          : isSchoolObligation
          ? value(feature.properties.name, "Unnamed School")
          : isTopographyProfile
          ? `Topography Profile · ${value(feature.properties.edge_type)} · ${value(feature.properties.edge_id)}`
          : isGradientSection
          ? `Gradient Section · ${value(feature.properties.gradient_band)}`
          : `${value(feature.properties.from_place_name, feature.properties.school_name || feature.properties.place_name || feature.properties.community_name || feature.properties.from_root_spine_name || feature.properties.from_place)} → ${value(feature.properties.to_place_name, feature.properties.parent_target_name || feature.properties.spine_name || feature.properties.to_root_spine_name || feature.properties.to_place)}`;
        const summary = document.createElement("span");
        summary.textContent = feature.properties.feature_type === "low-traffic-area"
          ? `candidate · ${value(feature.properties.portal_count, 0)} named portals`
          : feature.properties.feature_type === "low-traffic-area-portal"
          ? `portal · ${value(feature.properties.boundary_kind)}`
          : isSchoolStreet
          ? `${value(feature.properties.assessment_status)} · ${value(feature.properties.assessment_label)}`
          : isSchoolObligation
          ? `${value(feature.properties.service_status)} · ${value(feature.properties.access_point_status)} access point`
          : isTopographyProfile
          ? `${value(feature.properties.evidence_status)} · ${value(feature.properties.distance_m)} m`
          : isGradientSection
          ? `${value(feature.properties.length_m)} m · ${value(feature.properties.forward_gradient_pct)}% forward`
          : isNamedNetworkEvidence
          ? `${feature.properties.feature_type.replaceAll("-", " ")} · ${value(feature.properties.network_role, feature.properties.status)}`
          : `${value(feature.properties.distance_km, "Unknown distance")} · ${value(feature.properties.status)}`;
        button.append(title, summary);
        if (retainedTopography) {
          const warning = document.createElement("span");
          warning.className = "topography-warning";
          warning.textContent = "Elevation challenge retained";
          button.append(warning);
        }
        button.addEventListener("click", () => togglePin(feature.id));
        list.append(button);
      });
  }

  function renderCriteria(section) {
    const heading = document.querySelector("#criteria-heading");
    if (!heading) return;
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
      "layer-strategic-spines": ["strategic-spines"],
      "layer-spine-access-connections": ["spine-access-connections", "access-obligations", "spine-access-topography-warnings"],
      "layer-cross-spine-connectors": ["cross-spine-connectors"],
      "layer-a-road-spines": ["a-road-spines"],
      "layer-ncn-routes": ["ncn-route-evidence", "ncn-link-evidence"],
      "layer-urban-spines": ["urban-spines"],
      "layer-urban-classification-unknowns": ["urban-classification-unknowns"],
      "layer-low-traffic-areas": ["low-traffic-areas", "low-traffic-area-outlines"],
      "layer-low-traffic-area-portals": ["low-traffic-area-portals"],
      "layer-places": ["places"],
      "layer-schools": ["schools", "school-access-obligations", "school-access-connections", "school-access-topography-warnings", "school-access-gaps"],
      "layer-school-streets": ["school-street-assessments"],
      "layer-gradient-sections": ["gradient-sections", "topography-unavailable"],
      "layer-retail-centres": ["retail-centres"],
      "layer-healthcare": ["healthcare"],
      "layer-gaps-warnings": warningLayers,
      "layer-atm": ["atm-reference"]
    };
    Object.entries(groups).forEach(([controlId, layers]) => {
      const control = document.getElementById(controlId);
      if (!control) return;
      control.addEventListener("change", async () => {
        if (controlId === "layer-gradient-sections" && control.checked) {
          try {
            await ensureTopographyLoaded();
          } catch (error) {
            control.checked = false;
            document.querySelector("#terrain-status").textContent =
              `Topography layer unavailable. ${error.message}`;
          }
        }
        layers.forEach((layer) => {
          if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", control.checked ? "visible" : "none");
        });
        const legend = document.getElementById(`legend-${controlId.replace("layer-", "")}`);
        if (legend) legend.hidden = !control.checked;
      });
    });
    document.querySelectorAll(".info-button").forEach((button) => {
      const popover = document.getElementById(button.getAttribute("aria-controls"));
      const close = () => {
        popover.hidden = true;
        button.setAttribute("aria-expanded", "false");
      };
      button.addEventListener("click", () => {
        const open = popover.hidden;
        document.querySelectorAll(".layer-popover").forEach((item) => { item.hidden = true; });
        document.querySelectorAll(".info-button").forEach((item) => item.setAttribute("aria-expanded", "false"));
        popover.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
        if (open) {
          const rect = button.getBoundingClientRect();
          popover.style.top = `${Math.min(rect.top, window.innerHeight - popover.offsetHeight - 8)}px`;
        }
      });
      button.addEventListener("mouseleave", () => {
        if (!popover.matches(":hover")) close();
      });
      popover.addEventListener("mouseleave", close);
    });
    document.querySelector("#gradient-path-start").addEventListener("click", startPinnedPath);
    document.querySelector("#gradient-path-append").addEventListener("click", appendPinnedPath);
    document.querySelector("#gradient-path-remove").addEventListener("click", () => {
      setInspectionPath(state.inspectionPath.slice(0, -1));
    });
    document.querySelector("#gradient-path-reverse").addEventListener("click", () => {
      setInspectionPath(
        [...state.inspectionPath].reverse().map((item) => ({ ...item, reversed: !item.reversed }))
      );
    });
    document.querySelector("#gradient-path-reset").addEventListener("click", () => setInspectionPath([]));
    document.querySelector("#criteria-download").addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob(
        [JSON.stringify(data.criteria, null, 2)],
        { type: "application/json" }
      ));
      const link = document.createElement("a");
      link.href = url;
      link.download = "criteria-evidence.json";
      link.click();
      URL.revokeObjectURL(url);
    });
    document.querySelector("#terrain-mode").addEventListener("change", async (event) => {
      const status = document.querySelector("#terrain-status");
      if (!event.target.checked) {
        restoreTwoDimensionalMap();
        return;
      }
      try {
        if (!map.getSource("mapterhorn-dem")) {
          map.addSource("mapterhorn-dem", {
            type: "raster-dem",
            url: "https://tiles.mapterhorn.com/tilejson.json",
            tileSize: 512,
            attribution: "Terrain © Mapterhorn · England DTM © Environment Agency (OGL)"
          });
        }
        map.setTerrain({ source: "mapterhorn-dem", exaggeration: 1.8 });
        map.easeTo({ pitch: 55, duration: 700 });
        status.textContent =
          "3D terrain · 1.8× visual exaggeration · contextual only · Environment Agency 1 m DTM via Mapterhorn";
        terrainTimeout = window.setTimeout(
          () => restoreTwoDimensionalMap("Terrain provider timed out."),
          8000
        );
      } catch (error) {
        restoreTwoDimensionalMap(error.message);
      }
    });
    document.querySelector("#atm-upload").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      const status = document.querySelector("#atm-status");
      try {
        const uploaded = JSON.parse(await file.text());
        if (uploaded.type !== "FeatureCollection" || !Array.isArray(uploaded.features)) {
          throw new Error("Expected a GeoJSON FeatureCollection");
        }
        network.features = network.features.filter((feature) => feature.properties.feature_type !== "atm-reference");
        uploaded.features.forEach((feature, index) => {
          feature.id = feature.id || `local-atm-${index + 1}`;
          feature.properties = { ...(feature.properties || {}), feature_type: "atm-reference" };
          network.features.push(feature);
        });
        if (map.getSource("network")) map.getSource("network").setData(network);
        const control = document.querySelector("#layer-atm");
        control.disabled = false;
        control.checked = true;
        if (map.getLayer("atm-reference")) map.setLayoutProperty("atm-reference", "visibility", "visible");
        renderCards();
        status.textContent = `${uploaded.features.length} local ATM features loaded; uncheck ATM reference for the before view.`;
      } catch (error) {
        status.textContent = `ATM file was not loaded: ${error.message}`;
      }
    });
  }

  function extendBounds(bounds, coordinates) {
    if (typeof coordinates[0] === "number") bounds.extend(coordinates);
    else coordinates.forEach((item) => extendBounds(bounds, item));
  }

  map.on("load", () => {
    map.addSource("network", { type: "geojson", data: network });
    map.addSource("places", { type: "geojson", data: places });
    map.addSource("topography", {
      type: "geojson",
      data: data.topography_url
        ? { type: "FeatureCollection", features: [] }
        : {
          type: "FeatureCollection",
          features: network.features.filter((feature) =>
            ["gradient-section", "topography-profile"].includes(feature.properties.feature_type)
          )
        }
    });
    map.addSource("inspection-path", {
      type: "geojson",
      lineMetrics: true,
      data: { type: "FeatureCollection", features: [] }
    });
    map.addLayer({ id: "low-traffic-areas", type: "fill", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area"], paint: { "fill-color": "#7fb8c9", "fill-opacity": .24 } });
    map.addLayer({ id: "low-traffic-area-outlines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area"], paint: { "line-color": "#2f6474", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1, 13, 2], "line-opacity": .65 } });
    map.addLayer({ id: "low-traffic-area-portals", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area-portal"], layout: { visibility: "none" }, paint: { "circle-color": "#2874a6", "circle-radius": 7, "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    map.addLayer({ id: "places", type: "circle", source: "places", paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 4.5, 13, 6], "circle-color": "#17202a", "circle-stroke-color": "white", "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "strategic-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "strategic-spine"], paint: { "line-color": ["match", ["get", "spine_kind"], "a-road", "#a04000", "ncn", "#2471a3", "#566573"], "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4, 13, 6.5], "line-opacity": .82 } });
    map.addLayer({ id: "spine-access-connections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "spine-access-connection"], paint: { "line-color": "#168f7b", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 13, 4], "line-dasharray": [1.5, 1.25], "line-opacity": .85 } });
    map.addLayer({ id: "school-access-connections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "school-access-connection"], layout: { visibility: "none" }, paint: { "line-color": "#7d3c98", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 13, 4], "line-dasharray": [1.5, 1.25], "line-opacity": .85 } });
    map.addLayer({ id: "cross-spine-connectors", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "cross-spine-connector"], paint: { "line-color": "#7c4a93", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 3, 13, 5], "line-opacity": .8 } });
    map.addLayer({ id: "spine-access-topography-warnings", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "spine-access-connection"], ["in", ["get", "topography_comparison_status"], ["literal", ["original-retained-no-easier-option", "strategic-spine-retained"]]]], paint: { "line-color": "#f39c12", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4.5, 13, 7], "line-dasharray": [1, 1], "line-opacity": .9 } });
    map.addLayer({ id: "school-access-topography-warnings", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "school-access-connection"], ["in", ["get", "topography_comparison_status"], ["literal", ["original-retained-no-easier-option", "strategic-spine-retained"]]]], layout: { visibility: "none" }, paint: { "line-color": "#f39c12", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4.5, 13, 7], "line-dasharray": [1, 1], "line-opacity": .9 } });
    map.addLayer({ id: "access-obligations", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "access-obligation"], paint: { "circle-color": ["match", ["get", "service_status"], "served", "#1e8449", "served-provisional", "#f39c12", "network-gap", "#c0392b", "#7f8c8d"], "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5.5, 13, 7], "circle-stroke-color": "white", "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "school-access-obligations", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "school-access-obligation"], layout: { visibility: "none" }, paint: { "circle-color": ["match", ["get", "service_status"], "served", "#1e8449", "served-provisional", "#f39c12", "network-gap", ["match", ["get", "access_point_status"], "unresolved", "#7f8c8d", "#c0392b"], "#7f8c8d"], "circle-radius": 9, "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    map.addLayer({ id: "school-access-gaps", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "school-access-gap"], layout: { visibility: "none" }, paint: { "circle-color": ["match", ["get", "access_point_status"], "unresolved", "#7f8c8d", "inferred", "#f39c12", "#c0392b"], "circle-radius": 11, "circle-stroke-color": "#641e16", "circle-stroke-width": 2 } });
    map.addLayer({ id: "school-street-assessments", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "school-street-assessment"], layout: { visibility: "none" }, paint: { "circle-color": ["match", ["get", "assessment_status"], "green", "#1e8449", "amber", "#f39c12", "red", "#c0392b", "#7f8c8d"], "circle-radius": 12, "circle-stroke-color": "white", "circle-stroke-width": 3 } });
    map.addLayer({ id: "gradient-sections", type: "line", source: "topography", filter: ["==", ["get", "feature_type"], "gradient-section"], layout: { visibility: "none" }, paint: { "line-color": ["match", ["get", "gradient_band"], "gentle", "#eff3ff", "noticeable", "#bdd7e7", "steep", "#6baed6", "very-steep", "#3182bd", "severe", "#08519c", "#7f8c8d"], "line-width": 9, "line-opacity": .92 } });
    map.addLayer({ id: "gradient-section-highlight", type: "line", source: "topography", filter: ["==", ["id"], ""], paint: { "line-color": "#f4d03f", "line-width": 13, "line-opacity": .95 } });
    map.addLayer({ id: "topography-unavailable", type: "line", source: "topography", filter: ["all", ["==", ["get", "feature_type"], "topography-profile"], ["==", ["get", "evidence_status"], "evidence-unavailable"]], layout: { visibility: "none" }, paint: { "line-color": "#7f8c8d", "line-width": 8, "line-dasharray": [1, 1], "line-opacity": .9 } });
    map.addLayer({ id: "a-road-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "a-road-spine"], layout: { visibility: "none" }, paint: { "line-color": "#a04000", "line-width": 7, "line-opacity": .8 } });
    map.addLayer({ id: "ncn-route-evidence", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "ncn-route"], ["!=", ["coalesce", ["get", "ncn_evidence_role"], "established-route"], "connector-link"]], paint: { "line-color": "#2471a3", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 13, 4.5], "line-opacity": .78 } });
    map.addLayer({ id: "ncn-link-evidence", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "ncn-link"], paint: { "line-color": "#1f618d", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 2.5, 13, 4], "line-dasharray": [2.5, 1.5], "line-opacity": .82 } });
    map.addLayer({ id: "atm-reference", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "atm-reference"], layout: { visibility: "none" }, paint: { "line-color": "#2980b9", "line-width": 3, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "urban-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "urban-spine"], paint: { "line-color": "#513a63", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 3, 13, 4.75], "line-opacity": .82 } });
    map.addLayer({ id: "urban-classification-unknowns", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "urban-classification-unknown"], layout: { visibility: "none" }, paint: { "line-color": "#7f8c8d", "line-width": 5, "line-dasharray": [1, 1] } });
    map.addLayer({ id: "schools", type: "circle", source: "network", filter: ["all", ["==", ["get", "feature_type"], "school"], ["!=", ["get", "school_obligation_eligible"], true]], layout: { visibility: "none" }, paint: { "circle-color": "#7d3c98", "circle-radius": 6, "circle-stroke-color": "white", "circle-stroke-width": 1 } });
    map.addLayer({ id: "retail-centres", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "retail-centre"], layout: { visibility: "none" }, paint: { "circle-color": "#d35400", "circle-radius": 7, "circle-stroke-color": "white", "circle-stroke-width": 1 } });
    map.addLayer({ id: "healthcare", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "healthcare"], layout: { visibility: "none" }, paint: { "circle-color": "#c0392b", "circle-radius": 6, "circle-stroke-color": "white", "circle-stroke-width": 1 } });
    map.addLayer({ id: "gaps", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "gap"], paint: { "circle-color": "#c0392b", "circle-radius": 6 } });
    map.addLayer({ id: "crossing-warnings", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "crossing-warning"], paint: { "circle-color": "#f39c12", "circle-radius": 6, "circle-stroke-color": "#17202a", "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "connections-highlight", type: "line", source: "network", filter: ["==", ["id"], ""], paint: { "line-color": "#f4d03f", "line-width": 8 } });
    map.addLayer({ id: "inspection-path", type: "line", source: "inspection-path", paint: { "line-color": "#f4d03f", "line-width": 10, "line-opacity": .82 } });
    map.addLayer({
      id: "inspection-path-direction",
      type: "symbol",
      source: "inspection-path",
      layout: {
        "symbol-placement": "line-center",
        "text-field": ["concat", ["to-string", ["get", "inspection_order"]], " →"],
        "text-size": 15,
        "text-allow-overlap": true,
        "text-rotation-alignment": "map"
      },
      paint: {
        "text-color": "#17202a",
        "text-halo-color": "#fdfefe",
        "text-halo-width": 2
      }
    });
    const bounds = new maplibregl.LngLatBounds();
    [...network.features, ...places.features].forEach((feature) => {
      if (feature.geometry) extendBounds(bounds, feature.geometry.coordinates);
    });
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 60 });
    ["spine-access-connections", "school-access-connections", "cross-spine-connectors"].forEach((layer) => {
      map.on("mousemove", layer, (event) => { if (!state.pinned) showDetails(event.features[0].id); });
      map.on("mouseleave", layer, clearTransient);
      map.on("click", layer, (event) => togglePin(event.features[0].id));
    });
    map.on("mousemove", "places", (event) => showPlaceDetails(event.features[0]));
    map.on("mouseleave", "places", clearTransient);
    evidenceLayers.forEach((layer) => {
      if (!map.getLayer(layer)) return;
      map.on("mousemove", layer, (event) => { if (!state.pinned) showDetails(event.features[0].id); });
      map.on("mouseleave", layer, clearTransient);
      map.on("click", layer, (event) => togglePin(event.features[0].id));
    });
    document.documentElement.dataset.mapReady = "true";
  });

  renderCards();
  bindControls();
  updateGradientCandidate();
  renderLinearEvidence();
  const counts = data.layer_counts || {};
  document.querySelector("#layer-summary").textContent =
    `${counts.strategic_spines || 0} Strategic Spines · ${counts.spine_access_connections || 0} access connections · ` +
    `${counts.cross_spine_connectors || 0} Cross-Spine Connectors · ${counts.urban_spines || 0} Urban Main-Road Spines · ${counts.candidate_low_traffic_areas || 0} Candidate Low-Traffic Areas · ${counts.low_traffic_area_portals || 0} area portals · ` +
    `${counts.school_access_obligations || 0} School Access Obligations · ${counts.school_street_assessments || 0} School Street Candidate Assessments · ${counts.topography_profiles || 0} Topography Profiles · ${counts.gradient_sections || 0} Gradient Sections · ${counts.schools || 0} education sites · ${counts.retail_centres || 0} retail centres · ` +
    `${counts.healthcare || 0} healthcare sites`;
})();
