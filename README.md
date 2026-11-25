# Moon Base Battery + RTG Thermal Sizer

Python 3 tool for the **NASA Moon Base Challenge**: sizes a **lunar night battery pack** and **heat-only RTG thermal power** to hold battery boxes at Luke’s target temperature. Luke owns the design numbers; the program reads them from YAML (`owner`: `luke`, `cited-example`, or `TODO-luke`).

## Quick start

```bash
pip install -r requirements.txt
python3 sizer.py config.yaml          # stops until Luke fills TODO-luke design fields
python3 sizer.py examples/example_config.yaml   # EXAMPLE ONLY — placeholder geometry
```

## Config files

| File | Role |
|------|------|
| `config.yaml` | Luke’s inputs — **no placeholder geometry or RTG coupling** |
| `examples/example_config.yaml` | **EXAMPLE ONLY** — runnable placeholders for tests/PDF |

## Equations

1. **Night energy:** \(E_{\text{night}} = (P_{\text{load}} + P_{\text{heater}}) t_{\text{dark}}\)

2. **Capacity (discharge efficiency only):** \(C = E_{\text{night}} / (\mathrm{DoD} \cdot \eta_{\text{dis}})\)  
   If `eta_definition` is `round_trip`, \(\eta_{\text{dis}} = \sqrt{\eta_{\text{rt}}}\). Charge/array losses are noted separately until Luke chooses `eta_definition`.

3. **Pack mass:** \(\mathrm{mass} = C / \text{(specific energy)} \times \text{packaging factor}\)

4. **Internal waste heat (thermal credit):**  
   - Round-trip: \(Q_{\text{internal}} = P_{\text{load}} (1/\sqrt{\eta_{\text{rt}}} - 1)\)  
   - Discharge-only: \(Q_{\text{internal}} = P_{\text{load}} (1/\eta_{\text{dis}} - 1)\)  
   Both are reported until `eta_definition` is chosen.

5. **Box radiation** — per face (8×1.0×0.8×0.6 m example ≈ **30.08 m²** total including bottom):  
   outer/inner \(L \times H\), ends \(2 W H\) (reduced if tangential gap \(< W\)), top \(L W\) (\(F_{\text{sky}}=1\)), bottom \(L W\) (\(F_{\text{ground}}=1\) to regolith or deck).  
   Vertical faces: \(F_{\text{sky}}=F_{\text{ground}}=0.5\) (Wohl et al. 2024 NASA/TM-20240003496).  
   \(Q = \varepsilon_{\text{eff}} \sigma A \sum F_i (T^4 - T_i^4)\). Effective \(\varepsilon\) may include a **penetration/seam multiplier** (Gilmore p.165, TODO-luke).

6. **Legs as radiating fins** — 1-D discretized rod with conduction and sky/ground radiation (see Incropera & DeWitt, *Fundamentals of Heat and Mass Transfer*, fin analysis; Gilmore *Spacecraft Thermal Control Handbook* for lunar hardware context), **plus** conduction through footpad network.

7. **Regolith spreading (circular disk on half-space):** \(R = 1/(4 k a)\) with \(a=\sqrt{A/\pi}\) (constriction resistance — Incropera; Carslaw & Jaeger). Hayne et al. 2017 Table A1: **k ≈ 7.4×10⁻⁴ W/m·K** near surface, **3.4×10⁻³ W/m·K** at ~6–7 cm; example runs use surface k for foot contact.

8. **RTG thermal (not Slusser RHU-in-cavity):**  
   \(Q_{\text{RTG}} = \max(0, Q_{\text{loss}} - Q_{\text{internal}}) / f_{\text{coupling}}\)  
   Requires Luke’s `rtg.coupling_fraction` and `heat_path`. If unset → **Q_loss only** and message.  
   Informational helper: geometric fraction of isotropic center RTG flux onto inward box faces × absorptance (not a design default).

9. **Overheat:** if \(Q_{\text{internal}} > Q_{\text{loss}}\), report **Q_excess** (net need clamps to 0).

10. **Transient check (optional cp):** \(\Delta T \approx -Q_{\text{net}} t_{\text{dark}} / (m c_p)\); compare to `lipo_cold_limit_k`.

11. **Fallback modes** (`TODO-luke`):  
    - `same_pack_survival` — survival loads, same box geometry (less internal heat).  
    - `separate_pack` — scale box size from pack mass and volumetric energy density (iterates only in this branch).

## Tests

```bash
python3 -m pytest -q
```

## AI use

- **Implementation:** written with **AI assistance** (Cursor cloud agent on PR #1 fixes), **directed by Luke** via his Grok Bot assistant.  
- **Research:** cited-example parameters (Gilmore MLI \(\varepsilon^*\), Wohl view factors, Hayne regolith \(k\), Okishio contact \(h\), Colozza **tabular Ti k only**, Fixsen \(T_{\text{sky}}\), etc.) were gathered and labeled with **AI research assistance**; Luke must replace every `TODO-luke` and confirm `cited-example` vs `luke` before treating outputs as his design.

Luke must resolve every **`TODO-luke`** entry in `config.yaml` before running his real case.