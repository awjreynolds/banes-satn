# Area Deployments are isolated and publish evidence progressively

An Area Definition for one council, several councils or another coherent region
produces one independently reproducible Area Deployment. Generated GeoJSON,
GeoPackages, PDFs, ZIPs, evidence shards and site bundles are process artifacts and
do not belong in Git history; the repository retains governed definitions, compiler
code and compact deployment manifests. A lightweight Deployment Catalogue links
stable Area Deployment paths, so B&NES, WECA and later regions coexist without
overwriting or depending on one another.

Large optional evidence is published as content-addressed, zoom-dependent spatial
shards behind a small layer manifest. The initial Inspectable Review Map contains
only the strategic regional picture and named constituent-authority boundaries.
Selecting a layer loads its overview and active-view shards in parallel, reports
size and progress, and reuses best-effort browser caching. This was chosen over one
monolithic GeoJSON download, council-specific network forks, and committing generated
sites because the current B&NES site is already 156 MB and GitHub Pages limits one
published site to 1 GB.

Portable PDFs and Review Map ZIPs remain first-class Area Deployment artifacts.
GitHub Pages is an initial hosting adapter, not part of the Area Deployment identity;
publication must fail its configured size budget before a hosting limit is exceeded.
