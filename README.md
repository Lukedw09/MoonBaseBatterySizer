# Moon Base Battery + Pack Thermal Sizer

Python 3 tool for the **NASA Moon Base Challenge**: sizes **distributed lunar night battery packs** with **per-pack radiators** and **dawn wake solar panels**. Luke owns design numbers in YAML (`owner`: `luke`, `cited-example`, `placeholder`, `numerical`, `TODO-luke`).

## Quick start (CLI)

```bash
pip install -r requirements.txt
python3 sizer.py config.yaml          # blocks until Luke fills TODO-luke fields
python3 sizer.py examples/example_config.yaml --pdf examples/report.pdf
```

## Interactive UI (Streamlit)

1. Install dependencies: `pip install -r requirements.txt`
2. Start the app: `streamlit run app.py`
3. Sliders adjust loads, pack count, volumetric density, temperatures, and wake-panel inputs; results and the **n_packs** sweep refresh on **Run sizing**. Download the PDF from the button. Default config is **EXAMPLE ONLY** (`examples/example_config.yaml`).

## Layout

- **`layout.model: distributed_packs`** — several pack landers (box + legs + radiator); **no RTG deck** (`rtg.enabled: false`).
- **Box volume:** \(V_{\mathrm{pack}} = (C_{\mathrm{fleet}}/n_{\mathrm{packs}}) / \rho_{\mathrm{vol}}\) with Luke’s **`pack_volumetric_energy_density_wh_per_m3`**; L/W/H scale from reference aspect ratio.
- **Radiators:** passive — **`radiator_temperature_k` ≤ `box_target_temperature_k`**. Deployed area = **Table 16 factor × bare area**; mass = **12.3 kg/m² × deployed area** (Colozza 2020 Table 17). Night leak ∝ **ε_closed × σ × A_deployed × T⁴** when louvers closed.
- **Cold shutdown:** per-pack coast; **solar wake** panel (not pack discharge) provides warm-up power \(P_{\mathrm{wake}} = E_{\mathrm{warm}}/t_{\mathrm{wake}}\) over **`wake_up.warm_up_h`** (Luke: 6 h). Panel \(A = P/(1361\,\eta\,\cos\theta)\). Fleet wake energy and panel mass roll into **system mass**.

## Tests

```bash
python3 -m pytest -q
```

## AI use

Implementation with **AI assistance**, directed by Luke. Luke must resolve every **`TODO-luke`** before treating outputs as his design.