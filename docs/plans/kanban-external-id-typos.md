# Kanban External ID typos (found 2026-10-23)

Working list for fixing the source Kanban cards. Delete once the cards are
corrected and the converter has been rerun.

## Why it matters

The converter matches each Kanban card to an Estimates-sheet group by the
card's `External ID`, newest card first. Each estimate number is used once, so
when two cards share a number the newer card claims the estimate and the older
card is silently dropped (`select_spine`). Invoices join a job through its
estimate (the Estimates sheet's `Invoice Reference`), so a card with a typo'd
number gets the wrong estimate, and the real estimate and its invoice are lost.

Example (fixed in the dev DB 2026-10-23 by hand SQL): the Masjid Muhajireen
"design phase children's desks" card said 07226 instead of 07726. Job 07226
got Starlette Enterprises' $100 "christmas tree pole" estimate, invoice 10163
was dropped, and the real Starlette card vanished.

## How this list was built

All cards sharing an External ID (46 shared numbers) were compared to the
estimate the number points at, by customer (card `Name` vs the estimate's
contact, organisation and project) and date (card `Created at` vs estimate
`Date`, within 45 days). For a card that doesn't match, "probably meant" is a
real estimate for that customer dated within 10 days of the card.

**Limitation:** this only finds typos that collide with another card's number.
A typo pointing at an estimate number no other card uses won't appear here.

## Clear typos (the customer on the card doesn't match its estimate)

| Card says | Card (created) | Probably meant | Status |
|---|---|---|---|
| 07226 | Masjid Muhajireen (2026-01-20) | 07726 | dev DB fixed by SQL; source card still to fix |
| 06487 | Windy Chien (2024-04-23) | 06847 | |
| 07247 | Aviv Mano (2025-07-09) | 07427 | |
| 07268 | Hanna Lu (2025-10-28) | 07628 | |
| 07906 | Volley Automation (2024-11-13) | 07096 | |
| 07123 | Confidential Furniture (2025-02-19) | 07213 | |
| 07124 | SF Interiors Inc (2025-02-19) | 07214 | |
| 07061 | Franky Nguyen (2025-01-10) | 07161 | |
| 07115 | Hayward Rec and Park (2026-01-13) | 07715 | |
| 07419 | Life Cabinets (2025-08-21) | 07519 | |
| 05893 | Mohan Kinjarapu (2022-04-21) | 05894 | |
| 06578 | Bau Box (2023-10-13) | 06579 | |

## Wrong customer, correct estimate not found

| Card says | Card (created) | Estimate actually belongs to |
|---|---|---|
| 06610 | Tara Espinoza (2023-12-05) | Julie Rattaro |
| 06853 | Whitney Dafoe (2024-04-29) | Conrad Seto (card made the same day) |
| 07869 | Kiana Honarmand (2026-03-31) | Palace Games |

## Same customer, later card reused an older number

These could be follow-up jobs that reused the number, or typos. Either way the
converter keeps only the newest card, so the later card gets the old estimate
and the original card is dropped.

Likely estimate found:

| Card says | Card (created) | Possible estimate |
|---|---|---|
| 06150 | Martinelli (2023-02-22) | 06249 |
| 06608 | SFMOMA - Pegboard (2024-01-19) | 06693 |
| 07679 | Photomatica (2026-03-05) | 07788 |
| 07907 | Apple (2026-07-16) | 08053 |
| 07977 | Flow Control/TMI (2026-08-13) | 08104 |
| 05825 | Bagicha Socius (2022-04-29) | 05921 (weak match) |

No candidate found:

| Card says | Card (created) |
|---|---|
| 05867 | Re Union Creative laminate (2022-05-26) |
| 06546 | Hanbury (Shawna Mabie) (2023-12-12) |
| 06554 | Andre Raiche (2024-03-20) |
| 06564 | Clayton Controls (2024-02-01) |
| 06586 | GC Furniture (2024-01-09) |
| 07188 | Prysm (2025-03-27) |
| 07734 | CDS Distributing (2026-03-25) |
| 07767 | Richard Gaspar (Menches Tool and Die) (2026-07-27) |
| 07826 | Metal Tech BMD (2026-05-12) |

## Not typos

- **06150 "Martinelli recuts" (2023-01-10):** probably a genuine recut on the
  same job.
- **14 other shared numbers:** same customer and close dates (duplicate cards
  or same-day splits): 05871, 05993, 06251, 06659, 06981, 07023, 07087, 07322,
  07531, 07757, 07760, 08004, 08020, 08184.
- **05812 Mod Cabinetry:** two same-day cards (2022-04-21) for the right
  customer; the estimate is two months older (2022-02-22). Likely duplicate
  cards, not a typo.
- **Robot 6 (2026-06-24) and Martin (2022-09-06):** both have `-` as their
  External ID, which isn't an estimate number.

## Not yet done

- **Starlette Enterprises 07226 "christmas tree pole"** is missing from the dev
  DB; it only returns on a full regenerate after the 07226 → 07726 card fix
  (it converts as archived).
- **Converter-side check (optional):** report cards whose customer or date
  doesn't match their estimate, instead of accepting the match silently.
