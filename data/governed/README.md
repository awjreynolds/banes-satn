# Governed source extracts

## B&NES OS Open Roads, 7 April 2026

`banes-os-open-roads-2026-04-07.geojson` is the `road_link` layer from the
Great Britain OS Open Roads GeoPackage published on 7 April 2026, spatially
clipped to the governed B&NES boundary. Only the stable OS feature identifier,
road classification and geometry are retained because those are the fields the
compiler governs.

- Product: [OS Open Roads](https://www.ordnancesurvey.co.uk/products/os-open-roads)
- Download API: `https://api.os.uk/downloads/v1/products/OpenRoads/downloads?area=GB&format=GeoPackage&redirect`
- Classification vocabulary: A Road, B Road, Classified Unnumbered,
  Unclassified, Not Classified and Unknown
- Licence: Open Government Licence v3.0
- Attribution: Contains OS data © Crown copyright and database rights 2026.

The national package is not stored in this repository. The compact governed
extract is committed so snapshot acquisition and publication remain
reproducible without a multi-gigabyte download.
