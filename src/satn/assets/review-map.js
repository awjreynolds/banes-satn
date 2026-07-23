(() => {
  "use strict";
  const data = window.SATN_DATA;
  const network = data.network;
  const places = data.places;
  const state = { pinned: null, active: null };
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
      layers: [{ id: "osm", type: "raster", source: "osm" }]
    },
    center: [-2.5, 51.4],
    zoom: 10
  });
  window.SATN_REVIEW_MAP = map;
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
  }

  function renderCards() {
    const list = document.querySelector("#connection-list");
    list.replaceChildren();
    network.features
      .filter((feature) => ["gap", "strategic-spine", "access-obligation", "spine-access-connection", "school-access-obligation", "school-street-assessment", "school-access-connection", "school-access-gap", "branch-meeting-connection", "cross-spine-connector", "a-road-spine", "ncn-route", "ncn-link", "urban-spine", "urban-classification-unknown", "low-traffic-area", "low-traffic-area-portal", "crossing-warning", "school", "topography-profile", "gradient-section", "retail-centre", "healthcare", "atm-reference"].includes(feature.properties.feature_type))
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
        button.addEventListener("mouseenter", () => { if (!state.pinned) showDetails(feature.id); });
        button.addEventListener("mouseleave", clearTransient);
        button.addEventListener("focus", () => { if (!state.pinned) showDetails(feature.id); });
        button.addEventListener("click", () => togglePin(feature.id));
        list.append(button);
      });
    places.features.forEach((feature) => {
      const button = document.createElement("button");
      button.type = "button";
      button.id = `item-place-${feature.properties.place_id}`;
      button.className = "connection";
      button.dataset.featureId = feature.properties.place_id;
      button.dataset.featureType = "place";
      const title = document.createElement("strong");
      title.textContent = value(feature.properties.name, "Unnamed Network Place");
      const summary = document.createElement("span");
      summary.textContent = `Network Place · ${value(feature.properties.kind)}`;
      button.append(title, summary);
      button.addEventListener("mouseenter", () => showPlaceDetails(feature));
      button.addEventListener("mouseleave", clearTransient);
      button.addEventListener("focus", () => showPlaceDetails(feature));
      button.addEventListener("click", () => showPlaceDetails(feature));
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
      "layer-strategic-spines": ["strategic-spines"],
      "layer-spine-access-connections": ["spine-access-connections", "access-obligations", "spine-access-topography-warnings"],
      "layer-cross-spine-connectors": ["cross-spine-connectors", "branch-meeting-connections", "branch-meeting-topography-warnings"],
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
      control.addEventListener("change", () => {
        layers.forEach((layer) => {
          if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", control.checked ? "visible" : "none");
        });
        const legend = document.getElementById(`legend-${controlId.replace("layer-", "")}`);
        if (legend) legend.hidden = !control.checked;
      });
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
    map.addLayer({ id: "low-traffic-areas", type: "fill", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area"], paint: { "fill-color": "#5dade2", "fill-opacity": .45 } });
    map.addLayer({ id: "low-traffic-area-outlines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area"], paint: { "line-color": "#1b4f72", "line-width": 2.5, "line-opacity": .9 } });
    map.addLayer({ id: "low-traffic-area-portals", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "low-traffic-area-portal"], layout: { visibility: "none" }, paint: { "circle-color": "#2874a6", "circle-radius": 7, "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    map.addLayer({ id: "places", type: "circle", source: "places", paint: { "circle-radius": 7, "circle-color": "#17202a", "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    map.addLayer({ id: "strategic-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "strategic-spine"], paint: { "line-color": ["match", ["get", "spine_kind"], "a-road", "#a04000", "ncn", "#2471a3", "#566573"], "line-width": 8, "line-opacity": .85 } });
    map.addLayer({ id: "spine-access-connections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "spine-access-connection"], paint: { "line-color": "#16a085", "line-width": 6, "line-dasharray": [1, 1] } });
    map.addLayer({ id: "school-access-connections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "school-access-connection"], layout: { visibility: "none" }, paint: { "line-color": "#7d3c98", "line-width": 6, "line-dasharray": [1, 1] } });
    map.addLayer({ id: "cross-spine-connectors", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "cross-spine-connector"], paint: { "line-color": "#8e44ad", "line-width": 8, "line-opacity": .72 } });
    map.addLayer({ id: "branch-meeting-connections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "branch-meeting-connection"], paint: { "line-color": "#f39c12", "line-width": 7, "line-dasharray": [2, 1] } });
    map.addLayer({ id: "spine-access-topography-warnings", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "spine-access-connection"], ["in", ["get", "topography_comparison_status"], ["literal", ["original-retained-no-easier-option", "strategic-spine-retained"]]]], paint: { "line-color": "#f39c12", "line-width": 9, "line-dasharray": [1, 1], "line-opacity": .95 } });
    map.addLayer({ id: "school-access-topography-warnings", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "school-access-connection"], ["in", ["get", "topography_comparison_status"], ["literal", ["original-retained-no-easier-option", "strategic-spine-retained"]]]], layout: { visibility: "none" }, paint: { "line-color": "#f39c12", "line-width": 9, "line-dasharray": [1, 1], "line-opacity": .95 } });
    map.addLayer({ id: "branch-meeting-topography-warnings", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "branch-meeting-connection"], ["in", ["get", "topography_comparison_status"], ["literal", ["original-retained-no-easier-option", "strategic-spine-retained"]]]], paint: { "line-color": "#f39c12", "line-width": 9, "line-dasharray": [1, 1], "line-opacity": .95 } });
    map.addLayer({ id: "access-obligations", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "access-obligation"], paint: { "circle-color": ["match", ["get", "service_status"], "served", "#1e8449", "served-provisional", "#f39c12", "network-gap", "#c0392b", "#7f8c8d"], "circle-radius": 8, "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    map.addLayer({ id: "school-access-obligations", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "school-access-obligation"], layout: { visibility: "none" }, paint: { "circle-color": ["match", ["get", "service_status"], "served", "#1e8449", "served-provisional", "#f39c12", "network-gap", ["match", ["get", "access_point_status"], "unresolved", "#7f8c8d", "#c0392b"], "#7f8c8d"], "circle-radius": 9, "circle-stroke-color": "white", "circle-stroke-width": 2 } });
    map.addLayer({ id: "school-access-gaps", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "school-access-gap"], layout: { visibility: "none" }, paint: { "circle-color": ["match", ["get", "access_point_status"], "unresolved", "#7f8c8d", "inferred", "#f39c12", "#c0392b"], "circle-radius": 11, "circle-stroke-color": "#641e16", "circle-stroke-width": 2 } });
    map.addLayer({ id: "school-street-assessments", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "school-street-assessment"], layout: { visibility: "none" }, paint: { "circle-color": ["match", ["get", "assessment_status"], "green", "#1e8449", "amber", "#f39c12", "red", "#c0392b", "#7f8c8d"], "circle-radius": 12, "circle-stroke-color": "white", "circle-stroke-width": 3 } });
    map.addLayer({ id: "gradient-sections", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "gradient-section"], layout: { visibility: "none" }, paint: { "line-color": ["match", ["get", "gradient_band"], "gentle", "#eff3ff", "noticeable", "#bdd7e7", "steep", "#6baed6", "very-steep", "#3182bd", "severe", "#08519c", "#7f8c8d"], "line-width": 9, "line-opacity": .92 } });
    map.addLayer({ id: "topography-unavailable", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "topography-profile"], ["==", ["get", "evidence_status"], "evidence-unavailable"]], layout: { visibility: "none" }, paint: { "line-color": "#7f8c8d", "line-width": 8, "line-dasharray": [1, 1], "line-opacity": .9 } });
    map.addLayer({ id: "a-road-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "a-road-spine"], layout: { visibility: "none" }, paint: { "line-color": "#a04000", "line-width": 7, "line-opacity": .8 } });
    map.addLayer({ id: "ncn-route-evidence", type: "line", source: "network", filter: ["all", ["==", ["get", "feature_type"], "ncn-route"], ["!=", ["coalesce", ["get", "ncn_evidence_role"], "established-route"], "connector-link"]], paint: { "line-color": "#2471a3", "line-width": 5, "line-opacity": .9 } });
    map.addLayer({ id: "ncn-link-evidence", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "ncn-link"], paint: { "line-color": "#1f618d", "line-width": 5, "line-dasharray": [2, 1], "line-opacity": .95 } });
    map.addLayer({ id: "atm-reference", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "atm-reference"], layout: { visibility: "none" }, paint: { "line-color": "#2980b9", "line-width": 3, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "urban-spines", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "urban-spine"], paint: { "line-color": ["match", ["get", "official_classification"], "a-road", "#a04000", "b-road", "#8e44ad", "classified-unnumbered", "#5b2c6f", "#7f8c8d"], "line-width": 6 } });
    map.addLayer({ id: "urban-classification-unknowns", type: "line", source: "network", filter: ["==", ["get", "feature_type"], "urban-classification-unknown"], layout: { visibility: "none" }, paint: { "line-color": "#7f8c8d", "line-width": 5, "line-dasharray": [1, 1] } });
    map.addLayer({ id: "schools", type: "circle", source: "network", filter: ["all", ["==", ["get", "feature_type"], "school"], ["!=", ["get", "school_obligation_eligible"], true]], layout: { visibility: "none" }, paint: { "circle-color": "#7d3c98", "circle-radius": 6, "circle-stroke-color": "white", "circle-stroke-width": 1 } });
    map.addLayer({ id: "retail-centres", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "retail-centre"], layout: { visibility: "none" }, paint: { "circle-color": "#d35400", "circle-radius": 7, "circle-stroke-color": "white", "circle-stroke-width": 1 } });
    map.addLayer({ id: "healthcare", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "healthcare"], layout: { visibility: "none" }, paint: { "circle-color": "#c0392b", "circle-radius": 6, "circle-stroke-color": "white", "circle-stroke-width": 1 } });
    map.addLayer({ id: "gaps", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "gap"], paint: { "circle-color": "#c0392b", "circle-radius": 8 } });
    map.addLayer({ id: "crossing-warnings", type: "circle", source: "network", filter: ["==", ["get", "feature_type"], "crossing-warning"], paint: { "circle-color": "#f39c12", "circle-radius": 7, "circle-stroke-color": "#17202a", "circle-stroke-width": 2 } });
    map.addLayer({ id: "connections-highlight", type: "line", source: "network", filter: ["==", ["id"], ""], paint: { "line-color": "#f4d03f", "line-width": 11 } });
    const bounds = new maplibregl.LngLatBounds();
    [...network.features, ...places.features].forEach((feature) => {
      if (feature.geometry) extendBounds(bounds, feature.geometry.coordinates);
    });
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 60 });
    ["spine-access-connections", "school-access-connections", "cross-spine-connectors", "branch-meeting-connections"].forEach((layer) => {
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
  renderCriteria("connections");
  bindControls();
  const counts = data.layer_counts || {};
  document.querySelector("#layer-summary").textContent =
    `${counts.strategic_spines || 0} Strategic Spines · ${counts.spine_access_connections || 0} access connections · ` +
    `${counts.cross_spine_connectors || 0} Cross-Spine Connectors · ${counts.urban_spines || 0} Urban Main-Road Spines · ${counts.candidate_low_traffic_areas || 0} Candidate Low-Traffic Areas · ${counts.low_traffic_area_portals || 0} area portals · ` +
    `${counts.school_access_obligations || 0} School Access Obligations · ${counts.school_street_assessments || 0} School Street Candidate Assessments · ${counts.topography_profiles || 0} Topography Profiles · ${counts.gradient_sections || 0} Gradient Sections · ${counts.schools || 0} education sites · ${counts.retail_centres || 0} retail centres · ` +
    `${counts.healthcare || 0} healthcare sites`;
})();
