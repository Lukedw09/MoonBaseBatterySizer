# Moon Base Battery + Pack Thermal Sizer

Python 3 tool for the **NASA Moon Base Challenge**: sizes **distributed lunar night battery packs** with **per-pack radiators** and **dawn wake solar panels**. Luke owns design numbers in YAML (`owner`: `luke`, `cited-example`, `placeholder`, `numerical`, `TODO-luke`).

## Open the slider UI (easiest — no terminal)

1. On GitHub, click **Code → Download ZIP** and unzip the folder anywhere on your computer.
2. Open the unzipped project folder.
3. **Double-click** the launcher for your system:
   - **Windows:** `Open Battery Sizer.bat`
   - **macOS:** `Open Battery Sizer.command` (first time: right-click → Open if Gatekeeper asks)
   - **Linux:** `open_battery_sizer.sh` (or double-click if your desktop allows; otherwise run it from a terminal once)

The first launch creates a local `.venv` folder and installs dependencies; later launches are faster. Your browser should open the sizer automatically. If anything fails, the launcher window stays open with a plain-English message (install Python 3 from [python.org](https://www.python.org/downloads/) if prompted).

## Quick start (CLI)

```bash
pip install -r requirements.txt
python3 sizer.py config.yaml          # blocks until Luke fills TODO-luke fields
python3 sizer.py examples/example_config.yaml --pdf examples/report.pdf
```

## Interactive UI (manual Streamlit)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Default config in the app is **EXAMPLE ONLY** (`examples/example_config.yaml`). Sliders adjust loads, pack count, volumetric density, temperatures, and wake-panel inputs; **Run sizing** refreshes results and the **n_packs** sweep. Download the PDF from the button.

## Operating cases (owner: luke)

1. **5 kW all-night** — primary sizing, radiators reject excess heat, part-load break-even \(P_{\mathrm{be}}\) marks where louvers must close.
2. **Cold shutdown (P = 0)** — per-pack thermal coast through the night, then **dawn wake solar** panel per pack (not pack discharge).

There is **no separate low-load survival case**; radiator **louvers or a passive thermal switch must close** for cold shutdown so bare radiator area does not stay open (the model reports **louvers-stuck-open** coast vs closed coast and flags LiPo breach).

## Layout

- **`layout.model: distributed_packs`** — several pack landers (box + legs + radiator); **no RTG deck** (`rtg.enabled: false`).
- **Box volume:** \(V_{\mathrm{pack}} = (C_{\mathrm{fleet}}/n_{\mathrm{packs}}) / \rho_{\mathrm{vol}}\) with Luke’s **`pack_volumetric_energy_density_wh_per_m3`**; L/W/H scale from reference aspect ratio.
- **Radiators:** passive — **`radiator_temperature_k` ≤ `box_target_temperature_k`**. Deployed area = **Table 16 factor × bare area**; mass = **12.3 kg/m² × deployed area** (Colozza 2020 Table 17). Night leak ∝ **ε_closed × σ × A_deployed × T⁴** when louvers closed.
- **Cold shutdown:** per-pack coast; **solar wake** panel (not pack discharge) provides warm-up power \(P_{\mathrm{wake}} = E_{\mathrm{warm}}/t_{\mathrm{wake}}\) over **`wake_up.warm_up_h`** (Luke: 6 h). Panel \(A = P/(1361\,\eta\,\cos\theta)\). Fleet wake energy and panel mass roll into **system mass**.

## Tests

Install dependencies first (`pip install -r requirements.txt` or use a launcher). AppTest needs **streamlit** from that file.

```bash
python3 -m pytest -q
```

## AI use

Implementation with **AI assistance**, directed by Luke. Luke must resolve every **`TODO-luke`** before treating outputs as his design.