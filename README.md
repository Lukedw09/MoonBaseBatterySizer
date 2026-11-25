# Moon Base Battery + RTG Thermal Sizer

Small Python 3 tool for the **NASA Moon Base Challenge**: sizes a **lunar night battery pack** and the **heat-only RTG thermal power** needed to keep battery boxes warm with **zero electric heater load** (primary mode).

Luke (the student) owns the design numbers. The program **does not invent** inputs: every value lives in `config.yaml` with **units**, **source**, and **owner** (`luke`, `cited-example`, or `TODO-luke`).

## Quick start

```bash
pip install -r requirements.txt
python sizer.py config.yaml
```

This prints a results table and writes `report.pdf` (path overridable with `--pdf`).

## Equations (plain language)

1. **Night energy (electrical)**  
   \(E_{\text{night}} = (P_{\text{load}} + P_{\text{heater}}) \times t_{\text{dark}}\)  
   Energy the pack must deliver over the lunar night.

2. **Required stored capacity**  
   \(C = E_{\text{night}} / (\mathrm{DoD} \times \eta)\)  
   Accounts for depth of discharge and round-trip efficiency.

3. **Pack mass**  
   \(\mathrm{mass} = C / \text{(specific energy)} \times \text{packaging factor}\)  
   Specific energy is **pack-level** (Wh/kg), including connectors.

4. **Series cells**  
   \(N_{\text{series}} = \lceil V_{\text{bus}} / V_{\text{cell,nom}} \rceil\)  
   If **cell capacity (Ah)** is set, the tool also reports parallel strings.

5. **Thermal loss at the battery box** (fixed \(T_{\text{box}}\) from config)  
   - **Radiation:**  
     \(Q_{\text{rad}} = \varepsilon_{\text{eff}} \sigma A \big[ F_{\text{sky}}(T^4 - T_{\text{sky}}^4) + F_{\text{ground}}(T^4 - T_{\text{ground}}^4) \big]\)  
   - **Leg conduction path** (legs + footpad contact + regolith spreading, parallel legs):  
     Colozza-style \(Q = (T_{\text{box}} - T_{\text{surface}}) / R_{\text{total}}\)  
   - **Passthrough/seam** add-on (watts from config)

6. **RTG thermal (no electric output)**  
   - **Solve mode (default):** \(P_{\text{heater}} = 0\), \(Q_{\text{RTG}} = Q_{\text{loss}} / \text{coupling}\)  
   - **Fixed RTG mode:** if given \(Q_{\text{RTG}}\) is too small,  
     \(P_{\text{heater}} = \max(0, Q_{\text{loss}} - \text{coupling} \times Q_{\text{RTG}})\)  
     and that feeds back into step 1. With **fixed box geometry**, one iteration settles the heater feedback (mass does not resize the radiating area in the default config).

## Layout

| Path | Purpose |
|------|---------|
| `sizer.py` | Pure sizing/thermal functions + CLI |
| `config.yaml` | All inputs |
| `tests/` | `pytest` closed-form checks |
| `examples/report.pdf` | Sample PDF from default config |

## Sensitivity

The PDF includes **Q_RTG** and **pack mass** vs emittance, leg material, specific energy (150/200 Wh/kg), and load (5000 / 100 / 50 W).

## AI use

- **Code:** written with **AI assistance** (Cursor cloud agent), **directed by Luke** via his Grok Bot assistant.  
- **Research / cited defaults:** gathered and labeled by an **AI research assistant** from the sources noted in `config.yaml` (Colozza, Slusser, Fixsen, Hayne, Gilmore, Wohl, LEMS-A3 papers, etc.).  
- Items marked **`cited-example`** in the config and report are **examples, not Luke's final design choices**.

Luke must resolve every **`TODO-luke`** entry before treating outputs as his own design.