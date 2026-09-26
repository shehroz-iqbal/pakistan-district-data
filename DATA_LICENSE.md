# Data licences and attribution

The **code** in this repository is under the MIT licence (`LICENSE`). The **data** is derived
from the sources below; when you reuse it, keep their attribution.

| Data | Derived from | Licence | Attribution |
|---|---|---|---|
| All census figures (`data/processed/*.csv`, the workbook, `site/data/dashboard.json`) | Pakistan Bureau of Statistics, 7th Population and Housing Census 2023, district tables | Official statistics | "Source: Pakistan Bureau of Statistics, Census 2023" |
| (same) | CSV conversion by Fahad Mirza, [`pakistan_census_2023_tables`](https://github.com/fahad-mirza/pakistan_census_2023_tables) | MIT | Copyright (c) 2024 Fahad Mirza |
| District and province shapes (`*_2023.geojson`) | [geoBoundaries](https://www.geoboundaries.org/) gbOpen Pakistan ADM3, from Pathways Data Pvt. Ltd. based on PBS census maps | Open Database License (ODbL) 1.0: derived boundaries are shared under the same licence | "Boundaries: geoBoundaries (ODbL), rebuilt to 2023 census districts" |
| Matching hints (not published) | geoBoundaries gbOpen Pakistan ADM2 | Public domain | |
| Dashboard library (`site/vendor/d3.min.js`) | D3 v7.9.0 | ISC (`site/vendor/LICENSE-d3.txt`) | |

The corrections in `config/fixes.yml` and the crosswalks in `crosswalks/` are original work,
released under MIT with the code.
