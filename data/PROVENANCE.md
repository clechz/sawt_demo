# Menu provenance

Source: the attachment `restaurant-menu-complex.csv` on the [Sawt Challenge — Technical](https://app.notion.com/p/Sawt-Challenge-Technical-fe21da866603833d90a1011db9239f2d) page.

Downloaded 2026-10-11. Original file retained without modification.

- SHA256: `5d7411b0e2363fed35e7c42b4fc087594838461ad16c069bbae90cc82edc717a`
- Bytes: 374409
- Data rows: 1728
- Columns: 20
- Unique item IDs: 144
- Categories: 12
- Availability branches: `ruh_olaya`, `ruh_narjis`, `ruh_malqa`, `jed_rawdah`

Delivery zones, fees and ETAs are explicitly mocked in `sawt/domain.py`. The fixture's prices are interpreted as final customer prices; option deltas are additive. `item_price_with_option_sar` is a single-option reference value, not a second amount to add to the basket.
