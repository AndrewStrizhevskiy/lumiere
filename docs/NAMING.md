# The name "Lumière"

**Status: working name, not legally cleared.** This page records one focused, proportionate check made on **2026-10-10** and the decision taken. It is engineering due diligence, **not legal advice**, and it does not establish that the name is available.

## Decision
**Keep "Lumière" as a working name for this pre-1.0 project, without promoting it, and have a safer alternative ready** (outcome 2 of 3). Reasons: the name is a common word that is already used by several software products, including media players, and potential trademark filings in software classes could not be verified; but the project is small, non-commercial, and its display name is centralised (`kino_stream_ui/brand.py`), so changing it later is cheap. The technical names (`kino-stream`, `kino_stream`, …) were deliberately kept: they avoid collisions in package namespaces (see below) and keep existing installations working.

**Triggers to rename** (display name, repository and docs): a professional trademark search that finds a conflicting software/media registration; any complaint from a rights holder; before packaging for a distribution (Flatpak, AUR, .deb), before any 1.0 release, or before any promotion beyond this repository. **Candidate alternative** (only a placeholder, *not* checked for trademarks): **"Lanterne"** (French "lantern", a nod to the magic lantern). Free on PyPI and the AUR at the time of checking; the obvious domains are taken, so a domain cannot decide the name.

## Evidence (dates: 2026-10-10)
**Confirmed same-name software** (existence confirmed; none is affiliated with this project):
* *Lumiere*, a GNOME/Linux media player (xine front end), project page https://www.nongnu.org/lumiere/ — dormant, last news about 2004. Same category and platform: a searchability/confusion issue, probably a weak one.
* `vgarleanu/lumiere`, "Example video player built with MPV and Slint-UI" (Rust, 97 stars, last push 2022-02-14, not archived) — https://github.com/vgarleanu/lumiere. A prototype in the same category; also uses mpv.
* AUR package `lumiere` (a terminal tool for display brightness) — https://aur.archlinux.org/packages/lumiere. A name clash if this project were ever packaged for the AUR under that name.
* PyPI project `lumiere` exists — https://pypi.org/project/lumiere/. This project is not published on PyPI and its package is `kino-stream`.
* Unrelated products and research use the word (video-generation research models such as `lucidrains/lumiere-pytorch`, a 1990s Corel video suite, 3D/video web tools): crowding and search noise, not direct conflicts.

**Potential conflicts** (found only through secondary search results, **not verified in an official register**):
* US filings for LUMIERE reported by Justia, among them one in Class 9 for apparatus for recording/reproducing sound or images (serial 88643553; owner and status not verified) and a Class 41 film/TV production registration (no. 1979992): https://trademarks.justia.com/886/43/lumiere-88643553.html (the page itself could not be fetched; only search-result text was seen).
* Canada: a LUMIER/LUMIERE registration for downloadable educational app software was reported (TMA1263766); search at https://ised-isde.canada.ca/cipo/trademark-search/.
* The UK IPO journal returned several LUMIERE entries (not examined).

**Domains** (RDAP queries through https://rdap.org/ ; "registered" does not say who uses it, and an unregistered result is not a guarantee of availability): `lumiere.com` (registered 1995), `lumiere.org` (1998), `lumiere.dev` (2020), `lumiere.video` (2021), `lumiere.app` (2025), `lumiere.media`, `lumiere.watch`, `getlumiere.app` (2026) are registered; `lumiere.io` was inconclusive; `lumiereplayer.com` and `lumiere-player.org` returned "not found". Nothing was purchased or registered.

**Not checked / unverified:** the official registers were not searched programmatically (they are interactive): USPTO https://tmsearch.uspto.gov/, EUIPO https://euipo.europa.eu/eSearch/, WIPO https://branddb.wipo.int/, TMview https://www.tmdn.org/tmview/. Flathub and Snap showed no app named Lumière in the quick queries (Flathub returned no hits; Snap returned an unrelated name). GitHub's repository search was not completed (the API refused the query).

**Matters for professional legal advice:** whether any registered mark covers media-player or streaming software in the relevant classes and jurisdictions, likelihood of confusion with the products above, and whether the descriptive/common-word nature of "Lumière" affects protection. Until that is done the name must not be presented as cleared.

## What the project does meanwhile
The README and release notes say the name is not cleared and that the project is unaffiliated with other software called Lumière. The repository description names the product's function so it can be told apart in searches. No domain, package-registry entry or store listing is created under the name.
