# Smart Quality Gate Inspection — v6.2

Computer-vision Poka-Yoke chassis inspection system for the Tata Motors
HPCC Long Member Line. Two-camera RTSP capture, real-time checkpoint
detection, and a model-aware (VC-specific) checklist UI.

## What's new in v6.2

- **Reference-deck marker style** — the chassis panel now draws a dashed
  rectangle around each checkpoint (red = not detected, green = detected,
  with a small confirmed-check badge) plus a **yellow highlighted label
  box** with a thin leader line, matching the master PPTX checkpoint
  deck's red/yellow callout style. Box size per checkpoint is tunable via
  optional `w`/`h` fields in `config/settings.yaml`.
- **Label collision avoidance** — when several checkpoints sit close
  together, their yellow tags now stack cleanly instead of overlapping.
- **Text-only checklist panel** — the lower checklist no longer shows any
  photos. Each row is a compact checkbox + status dot + part name/id/
  location. The grid auto-balances rows/columns against the panel's
  actual available width *and height* so the whole checklist is visible
  **without scrolling** for normal checklist lengths.
- **Chassis image given much more room** — with the checklist panel far
  more compact, the camera/chassis row gets the majority of the vertical
  space, so the full reference photo renders large and uncropped.
- **Fixed a startup-bug class**: a Qt anti-pattern (calling `setText()`
  from inside `resizeEvent()`, which can re-trigger layout/resize
  recursively) was caught during testing and removed — checklist row
  labels are now truncated once at construction instead.
- **Fixed a font-metrics bug** where checkpoint label boxes were sized
  using the wrong (narrower) font, causing the rendered bold text to
  overflow past the box edge on the right-hand side of the chassis image.

## What's new in v6.1

- **Upper dashboard** — Settings, VIN, VC, Scan and Demo-mode controls in
  one bar under the title bar, alongside the live KPI tiles and verdict
  badge.
- **VC-specific checklists** — scanning a VC number resolves the vehicle
  model (`src/models.py`) and rebuilds the checklist for that model only.
- **Resizable vertical splitter** between the camera/chassis row and the
  checklist panel.
- **Hardened startup** — global exception hook (logs + friendly dialog
  instead of a silent crash); Linux's `xcb` Qt platform plugin override
  is no longer forced on Windows.

## Project layout

```
chassis_inspector/
├── main.py                  # entry point
├── requirements.txt
├── run.sh / run.bat          # Linux / Windows launchers
├── config/settings.yaml      # cameras, checkpoints (incl. box w/h), DB, line/station
├── assets/
│   ├── style.qss             # dark industrial theme
│   └── checkpoint_slides/    # PPTX-derived reference photos (slide_NN.png)
└── src/
    ├── main_window.py        # dashboard + camera/chassis + checklist layout
    │                          #   ChassisPhotoWidget = dashed-box/yellow-label overlay
    ├── checklist_panel.py    # text-only, no-scroll checkbox grid (this update)
    ├── models.py              # VC → VehicleModel → checklist resolution
    ├── checkpoints.py         # fixed CP-01..CP-11 detection registry
    ├── camera_widget.py / camera_worker.py
    ├── detector.py            # detection worker (template/YOLO/composite)
    ├── config_manager.py / database.py / logger.py
    ├── settings_dialog.py / stats_bar.py
    └── session.py / history_panel.py / vc_scan_widget.py  # unused legacy
                                                              modules kept
                                                              for reference,
                                                              not imported
```

## Running

```bash
pip install -r requirements.txt
python main.py        # or ./run.sh (Linux) / run.bat (Windows)
```

Logs are written to `logs/app.log`; the SQLite inspection database is at
`logs/inspector.db` (or MS SQL Server if configured in `config/settings.yaml`).

## Adding a new vehicle model / checklist

Edit `src/models.py`:

1. Add a `ChecklistItem(...)` list (or reuse `_BASE_CHECKLIST` /
   `_SHORT_CHECKLIST`).
2. Register it in `VEHICLE_MODELS` under the VC prefix that should match
   it, e.g. `"5523": VehicleModel(code="5523", name="...", checklist=[...])`.
3. If a checkpoint needs a new reference photo (for the settings-dialog
   preview / future use), drop a `slide_NN.png` into
   `assets/checkpoint_slides/` where `NN` matches the checklist item id
   (`CL-07` → `slide_07.png`).
4. To fine-tune where its dashed box sits on the full chassis reference
   image, edit `x`/`y` (centre, 0–1 normalised) and `w`/`h` (box size,
   0–1 normalised fraction of the image) for that checkpoint in
   `config/settings.yaml` (or via the in-app Settings dialog for `x`/`y`).

