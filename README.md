# Helicoid focus scale

GUI tool that generates a **true 1:1** printable focus scale for a helicoid / lens setup. Enter barrel diameter, throw, extension, and optics params; get a PDF (or PNG strip) with distance marks you can cut and wrap onto the helicoid.

## Requirements

- Python 3.10+
- [Pillow](https://pillow.readthedocs.io/) ≥ 10
- tkinter (usually bundled with Python; on Linux you may need `python3-tk`)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python focus_scale.py
```

Use **Generate…** to save a PDF or PNG. The save dialog suggests a filename that encodes the main params, e.g.:

`focus_scale_f135_d80_t300_e30_ffd131.3_fixed.pdf`

## Scale length

Printed arc length (mm):

\[
L = \frac{\text{throw}^\circ}{360} \times \pi \times \text{diameter}
\]

Throw may exceed 360° for multi-turn helicoids.

## Optics model

- With **error = 0**, infinity is at full retract.
- Extension past infinity: \(\delta = f^2 / (u - f)\), where \(u\) is object distance and \(f\) is focal length.
- **Positive error**: helicoid sits too far from the film/sensor → infinity is unreachable (retract focuses closer than ∞).
- **Negative error**: infinity falls partway into the throw.
- **FFD** (focal flange distance) is recorded on the PDF for reference; mark positions are driven by focal length, extension, and error.

## Features

- **1:1 PDF** — never scaled down to fit. Long scales tile into rows; print at 100%.
- **Letter / A4**, portrait or landscape as needed.
- **Page joins** — continuing rows get a 5 mm striped glue tab labelled **A, B, …**. Glue the next row onto the matching tab.
- **Circumference wraps** — when length exceeds \(\pi \times d - \text{buffer}\) (default buffer 5 mm), a forced break uses a **detached W1, W2, …** marker (not a glue tab).
- **Mark modes**
  - **fixed** — comma-separated distances (metres).
  - **dynamic** — nice round distances, thinned by min spacing and focus Δ.
- **Live preview** — exact print proportions; uniform zoom only.
- **Appearance** — text/tick colours, glue-stripe colour, system font picker with fuzzy search (default Helvetica Neue, fallback Arial).

Hover the **ⓘ** icons in the UI for per-field help.

## Main parameters

| Parameter | Unit | Role |
|-----------|------|------|
| Helicoid diameter | mm | Barrel OD; sets circumference / scale length |
| Helicoid extension | mm | Axial travel over full throw |
| Focal flange distance | mm | Metadata on PDF |
| Throw | deg | Angular travel (may be &gt; 360) |
| Focal distance | mm | Lens focal length |
| Scale height | mm | Strip height at 1:1 |
| Error | mm | Axial mounting offset (see optics) |
| Wrap buffer | mm | Break every circumference − buffer |

## Printing

1. Export PDF.
2. Print at **100% / actual size** (disable “fit to page”).
3. For multi-row pages, cut rows and glue onto the matching **A/B…** striped tabs.
4. At **W**n breaks, treat as a full-turn wrap (overlap/buffer), not a page glue join.
