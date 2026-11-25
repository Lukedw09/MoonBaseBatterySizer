# Moon Base Battery + Pack Thermal Sizer

Python 3 tool for the **NASA Moon Base Challenge**: sizes **distributed lunar night battery packs** with **per-pack radiators** rejecting excess internal heat. Luke owns design numbers in YAML (`owner`: `luke`, `cited-example`, `TODO-luke`, `placeholder`).

## Quick start

```bash
pip install -r requirements.txt
python3 sizer.py config.yaml          # stops until Luke fills TODO-luke design fields
python3 sizer.py examples/example_config.yaml --pdf examples/report.pdf
```

## Layout model

- **`layout.model: distributed_packs`** (Luke’s choice): several smaller packs across the base, each on its own legs — **no central RTG deck**.
- **`geometry.n_packs`**: fleet count (TODO-luke in `config.yaml`; example uses 8).
- Per-pack box **L/W/H** scale as **n^(-1/3)** when total fleet capacity is split across `n_packs` (`scale_dims_with_n_packs: true`).
- Box faces: **top** → sky (F=1), **vertical** sides 0.5 sky / 0.5 ground, **bottom** → regolith; packs are far apart (no mutual irradiation).
- Optional legacy **`ring_rtg`** layout remains in code for regression.

## Radiators

Each pack rejects **Q_excess/n_packs** at night design:

\[
A_{\mathrm{rad}} = \frac{Q_{\mathrm{excess,pack}}}{\varepsilon_{\mathrm{rad}}\,\sigma\,(T_{\mathrm{rad}}^4 - T_{\mathrm{env,eff}}^4)}
\]

Example cites **Z-93 ε≈0.92** (Kauder 2005). Mass uses **Colozza 2020 Table 17** louvered radiator **4.5 kg/m²** with **+30% area** multiplier. **Closed radiator night leak** per pack is an input (VIPER valve context — Bluethmann 2024 p.13).

**System mass** ≈ pack mass (cells) + radiator mass + optional leg structure mass per pack.

## Equations (battery + legs)

1. **Night energy:** \(E_{\text{night}} = (P_{\text{load}} + P_{\text{heater}}) t_{\text{dark}}\)
2. **Capacity:** \(C = E_{\text{night}} / (\mathrm{DoD}\,\eta_{\text{dis}})\) with Luke’s **`eta_definition: discharge`**.
3. **Internal heat:** \(Q_{\text{internal}} = P_{\text{load}}(1/\eta - 1)\) (discharge definition).
4. **Legs:** radiating-fin BVP (`scipy.integrate.solve_bvp`); regolith spreading \(R=1/(4ka)\) (Hayne et al. 2017).
5. **Cold shutdown:** per-pack lumped coast with \(Q_{\text{loss}}(T)\); dawn warm-up heater energy (solar wake-up before charge).
6. **RTG:** optional module (`rtg.enabled: false` in Luke layout); kept for legacy / fixed_rtg tests.

## Tests

```bash
python3 -m pytest -q
```

## AI use

Implementation and cited-parameter research with **AI assistance** (Cursor cloud agent), directed by Luke via Grok Bot. Luke must resolve every **`TODO-luke`** before treating outputs as his design.