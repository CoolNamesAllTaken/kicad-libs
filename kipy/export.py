#!/usr/bin/env python3
# ===========================================================================
# export.py — KiCAD Python export script
# Translated from config.kibot.yml
#
# Usage:
#   python3 export.py <board.kicad_pcb> <schematic.kicad_sch>
#
# Environment variables (override project text variables):
#   PCBA_PN   — Assembly part number  (default: from .kicad_pro, then PROJ)
#   PCBA_REV  — Assembly revision     (default: from .kicad_pro, then A)
#   PCB_PN    — Fab part number       (default: same as PCBA_PN)
#   PCB_REV   — Fab revision          (default: same as PCBA_REV)
#
# File naming:
#   Assembly outputs  -> PCBA_PN-PCBA_REV-<filename>
#   Fab outputs       -> PCB_PN-PCB_REV-<filename>
#
# Notes on the KiCAD Python API:
#   The new KiCAD IPC Python API (docs.kicad.org/kicad-python-main/) does not
#   yet expose plot/export functionality — it covers board data manipulation
#   only. Export operations use two mechanisms:
#
#     1. kicad-cli subprocess calls — covers gerbers, drill, drill maps, PDF,
#        STEP, position, BOM, schematic PDF, ERC, DRC.
#
#     2. pcbnew scripting module — the established KiCAD scripting API used
#        internally by KiBot and other tools. Used here for IPC-D-356 netlist
#        export (ExportToIpcD356 / IPC356D_WRITER), which has no kicad-cli
#        equivalent.
#
#   The pcbnew module ships with KiCAD. Typical locations:
#     macOS:  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/
#             Versions/Current/lib/python3.x/site-packages/
#     Linux:  /usr/lib/kicad/lib/python3/dist-packages/
#   Add the appropriate path to PYTHONPATH if `import pcbnew` fails.
# ===========================================================================

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="KiCAD export script — equivalent to running KiBot with config.kibot.yml",
    )
    p.add_argument("pcb_file", type=Path, help="Board file (.kicad_pcb)")
    p.add_argument("sch_file", type=Path, help="Schematic file (.kicad_sch)")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Override output directory (default: <pcb_dir>/exports)")
    p.add_argument("--copper-layers", default=None,
                   help="Override detected copper layers (comma-separated, e.g. F.Cu,B.Cu)")
    p.add_argument("--ibom-script", type=Path, default=None,
                   help="Path to generate_interactive_bom.py")
    p.add_argument("--panel", action="store_true",
                   help="Panel export mode: skip ERC/assembly/engineering, "
                        "create <pcb_prefix>-with-panel.zip")
    p.add_argument("--project-dir", type=Path, default=None,
                   help="Project root to search for impedance_control.xlsx "
                        "(default: directory containing the PCB file)")
    p.add_argument("--jlcpcb", action="store_true",
                   help="Generate JLCPCB-specific outputs in special/jlcpcb/")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print(f"\n=== {title} ===")


def note(msg: str) -> None:
    print(f"    NOTE: {msg}")


def run(cmd: list[str | Path], **kwargs) -> None:
    """Run a subprocess command, raising on failure."""
    print("   $", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def require_tool(name: str) -> None:
    if not shutil.which(name):
        print(f"ERROR: '{name}' not found in PATH", file=sys.stderr)
        sys.exit(1)


def read_project_text_vars(pcb_file: Path) -> dict[str, str]:
    """Read text_variables from the .kicad_pro file alongside the PCB."""
    pro_file = pcb_file.parent / (pcb_file.stem + ".kicad_pro")
    if not pro_file.is_file():
        return {}
    try:
        data = json.loads(pro_file.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.get("text_variables", {}).items()}
    except (json.JSONDecodeError, OSError):
        return {}


def detect_copper_layers(pcb_file: Path) -> str:
    """Parse .kicad_pcb and return comma-separated copper layers in board order.

    KiCad layer numbering: F.Cu=0, In1.Cu-In30.Cu=1-30, B.Cu=31.
    Sorting by integer ensures F.Cu first, inner layers in order, B.Cu last.
    """
    text = pcb_file.read_text(encoding="utf-8")
    pattern = re.compile(r'\(\s*(\d+)\s+"([^"]+\.Cu)"\s+\w+')
    seen: set[str] = set()
    layers: list[tuple[int, str]] = []
    for m in pattern.finditer(text):
        num, name = int(m.group(1)), m.group(2)
        if name not in seen:
            seen.add(name)
            layers.append((num, name))
    copper_layers = [name for _, name in layers]
    return ",".join(copper_layers)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight_erc(sch_file: Path, out_base: Path, prefix: str) -> None:
    """
    kibot: preflight.erc: true
    Runs ERC on the schematic and writes a report.
    """
    section("Preflight: ERC")
    out_base.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "sch", "erc",
        "--output", out_base / f"{prefix}-erc.txt",
        sch_file,
    ])


def preflight_drc(pcb_file: Path, out_base: Path, prefix: str) -> None:
    """
    kibot: preflight.drc: true
    kibot: preflight.fill_zones: true           --refill-zones
    kibot: preflight.update_pcb_characteristics  --save-board
    """
    section("Preflight: DRC")
    run([
        "kicad-cli", "pcb", "drc",
        "--output", out_base / f"{prefix}-drc.txt",
        "--format", "report",
        "--schematic-parity",
        "--refill-zones",
        "--save-board",
        pcb_file,
    ])


# ---------------------------------------------------------------------------
# Fabrication outputs
# ---------------------------------------------------------------------------

def rename_board_outputs(directory: Path, board_name: str, prefix: str) -> None:
    """Rename kicad-cli outputs from <board_name>* to <prefix>*.

    kicad-cli names directory-mode outputs using the PCB file stem. This
    renames them to match the desired prefix scheme.
    """
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.name.startswith(board_name):
            new_name = prefix + f.name[len(board_name):]
            f.rename(f.parent / new_name)


def export_gerbers(pcb_file: Path, dir_gerber: Path, copper_layers: str, prefix: str) -> None:
    """
    kibot: type: gerber
    Options translated:
      subtract_mask_from_silk: true     --subtract-soldermask
      use_gerber_x2_attributes: true    X2 is on by default in kicad-cli
      use_gerber_net_attributes: false  --no-netlist
      use_protel_extensions: false      --no-protel-ext
      gerber_precision: 4.5             --precision 5 (5 decimal digits)
      plot_sheet_reference: true        --include-border-title
    Note: line_width, tent_vias, exclude_pads_from_silkscreen are board-level
    plot settings with no kicad-cli flag; configure them in the PCB file.
    Note: create_gerber_job_file is generated automatically by kicad-cli.
    """
    section("Gerbers")
    dir_gerber.mkdir(parents=True, exist_ok=True)
    layers = f"{copper_layers},F.Mask,B.Mask,F.SilkS,B.SilkS,F.Fab,B.Fab,F.Paste,B.Paste,Edge.Cuts,User.Drawings,User.Comments"
    run([
        "kicad-cli", "pcb", "export", "gerbers",
        "--output", str(dir_gerber) + "/",
        "--layers", layers,
        "--subtract-soldermask",
        "--no-protel-ext",
        "--include-border-title",
        pcb_file,
    ])
    rename_board_outputs(dir_gerber, pcb_file.stem, prefix)


def export_drill(pcb_file: Path, dir_drill: Path, prefix: str) -> None:
    """
    kibot: type: excellon, pth_and_npth_single_file: true (merged, the default)
    Generates drill files with both PDF and DXF maps.
    """
    section("Drill files (PDF map)")
    dir_drill.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "pcb", "export", "drill",
        "--output", str(dir_drill) + "/",
        "--format", "excellon",
        "--excellon-units", "mm",
        "--generate-map",
        "--map-format", "pdf",
        pcb_file,
    ])

    section("Drill files (DXF map)")
    run([
        "kicad-cli", "pcb", "export", "drill",
        "--output", str(dir_drill) + "/",
        "--format", "excellon",
        "--excellon-units", "mm",
        "--generate-map",
        "--map-format", "dxf",
        pcb_file,
    ])
    rename_board_outputs(dir_drill, pcb_file.stem, prefix)


def export_ipc_d356(pcb_file: Path, dir_fab: Path, prefix: str) -> None:
    """
    kibot: type: netlist, format: ipc
    IPC-D-356 netlist via the pcbnew scripting module.
    kicad-cli has no IPC-D-356 command (ipc2581 is a different standard).
    """
    section("IPC-D-356 Netlist")
    try:
        import pcbnew  # type: ignore[import]
    except ImportError:
        note("pcbnew module not found — skipping IPC-D-356 export.")
        note("Add KiCAD's Python site-packages to PYTHONPATH to enable:")
        note("  macOS: /Applications/KiCad/KiCad.app/Contents/Frameworks/"
             "Python.framework/Versions/Current/lib/python3.x/site-packages/")
        note("  Linux: /usr/lib/kicad/lib/python3/dist-packages/")
        return

    out_file = dir_fab / f"{prefix}-netlist.ipc"
    board = pcbnew.LoadBoard(str(pcb_file))

    # IPC356D_WRITER is available in KiCAD 7+.
    # In older versions, use board.ExportToIpcD356(str(out_file)) if available.
    try:
        writer = pcbnew.IPC356D_WRITER(board)
        writer.Write(str(out_file))
        print(f"     {out_file}")
    except AttributeError:
        # Fallback for older pcbnew versions
        try:
            board.ExportToIpcD356(str(out_file))
            print(f"     {out_file}")
        except AttributeError:
            note("pcbnew.IPC356D_WRITER / board.ExportToIpcD356 not available "
                 "in this KiCAD version.")


def export_drawing(
    pcb_file: Path,
    dir_fab: Path,
    prefix: str,
    copper_layers: str,
) -> None:
    """
    kibot: type: pcb_print — multi-page fabrication drawing PDF.
    KiBot's pcb_print can composite multiple layers per page in one shot.
    kicad-cli exports one page at a time, so we generate individual PDFs and
    merge them with pdfunite (poppler) or gs (ghostscript).

    Pages defined in config.kibot.yml:
      1. Primary Side   — F.Cu + F.Mask + F.SilkS + F.Paste + Edge.Cuts + User.Drawings
      2. Secondary Side — B.Cu + B.Mask + B.SilkS + B.Paste + Edge.Cuts
      3. Primary Paste  — F.Paste + Edge.Cuts
      4. Secondary Paste — B.Paste + Edge.Cuts
      5+. Copper Layer  — one page per copper layer (repeat_for_layer / repeat_layers: copper)
    """
    section("Technical Drawing PDF")

    pages: list[tuple[str, str, str]] = [
        ("primary-side",    "F.Cu,F.Mask,F.SilkS,F.Paste,Edge.Cuts,User.Drawings", "Primary Side"),
        ("secondary-side",  "B.Cu,B.Mask,B.SilkS,B.Paste,Edge.Cuts",               "Secondary Side"),
        ("primary-paste",   "F.Paste,Edge.Cuts",                                    "Primary Paste"),
        ("secondary-paste", "B.Paste,Edge.Cuts",                                    "Secondary Paste"),
    ]

    # Add one page per copper layer (kibot: repeat_for_layer / repeat_layers: copper)
    for layer in copper_layers.split(","):
        safe = layer.replace(".", "")
        pages.append((f"copper-{safe}", f"{layer},Edge.Cuts", layer))

    page_pdfs: list[Path] = []
    for name, layers, sheet_name in pages:
        out = dir_fab / f"{prefix}-{name}.pdf"
        run([
            "kicad-cli", "pcb", "export", "pdf",
            "--output", out,
            "--layers", layers,
            "--include-border-title",
            "--define-var", f"EXPORT_SHEET={sheet_name}",
            "--mode-single",
            pcb_file,
        ])
        page_pdfs.append(out)

    merged = dir_fab / f"{prefix}-fabrication.pdf"
    if shutil.which("pdfunite"):
        run(["pdfunite", *page_pdfs, merged])
        for p in page_pdfs:
            p.unlink(missing_ok=True)
        print(f"    Merged  {merged}")
    elif shutil.which("gs"):
        run([
            "gs", "-dBATCH", "-dNOPAUSE", "-q",
            "-sDEVICE=pdfwrite",
            f"-sOutputFile={merged}",
            *page_pdfs,
        ])
        for p in page_pdfs:
            p.unlink(missing_ok=True)
        print(f"    Merged (ghostscript)  {merged}")
    else:
        note("pdfunite/gs not found — individual page PDFs left in place.")
        note("Install poppler-utils (brew install poppler) to auto-merge.")


# ---------------------------------------------------------------------------
# Assembly outputs
# ---------------------------------------------------------------------------

def export_ibom(
    pcb_file: Path,
    dir_assembly: Path,
    prefix: str,
    ibom_script: Path | None = None,
) -> None:
    """
    kibot: type: ibom — Interactive HTML BOM.
    ibom is not part of kicad-cli; it requires the InteractiveHtmlBom plugin:
      https://github.com/openscopeproject/InteractiveHtmlBom
    Set --ibom-script or the IBOM_SCRIPT env var to the path of
    generate_interactive_bom.py to enable.
    Options:
      include_tracks: true     --include-tracks
      include_nets: true       --include-nets
      blacklist_empty_val: true  --blacklist-empty-val
      dark_mode: true          --dark-mode
      highlight_pin1: true     --highlight-pin1 all
    """
    section("Interactive HTML BOM")

    script = ibom_script or Path("/usr/local/bin/generate_interactive_bom")
    dir_assembly.mkdir(parents=True, exist_ok=True)
    os.environ['INTERACTIVE_HTML_BOM_NO_DISPLAY'] = '' # Tell interactive html bom we have no display.
    run([
        script,
        "--dest-dir", dir_assembly,
        "--no-browser",
        "--name-format", f"{prefix}-ibom",
        "--include-tracks",
        "--include-nets",
        "--blacklist-empty-val",
        "--dark-mode",
        "--highlight-pin1", "all",
        pcb_file,
    ])


def export_positions(pcb_file: Path, dir_pnp: Path, prefix: str) -> None:
    """
    kibot: type: position, format: ASCII, only_smd: false
    Standard pick-and-place CSV (both sides, all components including THT).
    """
    section("Pick and Place")
    dir_pnp.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "pcb", "export", "pos",
        "--output", dir_pnp / f"{prefix}-pos.csv",
        "--format", "csv",
        "--units", "mm",
        "--side", "both",
        pcb_file,
    ])


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------

def export_bom(sch_file: Path, dir_assembly: Path, prefix: str) -> None:
    """
    kibot: type: bom — BOM CSV.
    group_fields: [Manufacturer, MPN]   --group-by "Manufacturer,MPN"
    Columns and labels mirror config.kibot.yml exactly.
    Note: csv.hide_pcb_info and csv.quote_all have no kicad-cli equivalents;
    the output is standard CSV. Use a post-processing step if needed.
    """
    section("BOM CSV")
    dir_assembly.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "sch", "export", "bom",
        "--output", dir_assembly / f"{prefix}-bom.csv",
        "--fields",
        "Reference,Value,Footprint,QUANTITY,DNP,Standard Cost,"
        "Manufacturer,MPN,LCSC PN,Note",
        "--labels",
        "Reference,Value,Footprint,Quantity,Populate,Standard Cost,"
        "Manufacturer,MPN,LCSC PN,Note",
        "--group-by", "Manufacturer,MPN",
        "--ref-range-delimiter", "", # Don't use a delimiter; list all designators in the Designator column.
        sch_file,
    ])


# ---------------------------------------------------------------------------
# Engineering outputs
# ---------------------------------------------------------------------------

def export_schematic_pdf(sch_file: Path, dir_engineering: Path, prefix: str) -> None:
    """kibot: type: pdf_sch_print"""
    section("Schematic PDF")
    dir_engineering.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "sch", "export", "pdf",
        "--output", dir_engineering / f"{prefix}-schematic.pdf",
        sch_file,
    ])


def export_3d_step(pcb_file: Path, dir_engineering: Path, prefix: str) -> None:
    """
    kibot: type: export_3d
    include_silkscreen: true   --include-silkscreen
    include_pads: true         --include-pads
    include_soldermask: true   --include-soldermask
    substitute_models: true    --subst-models
    """
    section("3D Model (STEP)")
    run([
        "kicad-cli", "pcb", "export", "step",
        "--output", dir_engineering / f"{prefix}.step",
        "--include-silkscreen",
        "--include-pads",
        "--include-soldermask",
        "--subst-models",
        pcb_file,
    ])


# ---------------------------------------------------------------------------
# Specialized outputs
# ---------------------------------------------------------------------------

def export_positions_openpnp(pcb_file: Path, dir_openpnp: Path, prefix: str) -> None:
    """
    kibot: type: position, bottom_negative_x: true, include_virtual: true
    --bottom-negate-x mirrors bottom-side component X coordinates for OpenPNP.
    Note: include_virtual has no kicad-cli flag; virtual footprints are included
    by default when --smd-only is not passed.
    """
    section("Pick and Place (OpenPNP)")
    dir_openpnp.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "pcb", "export", "pos",
        "--output", dir_openpnp / f"{prefix}-pos-openpnp.csv",
        "--format", "csv",
        "--units", "mm",
        "--side", "both",
        "--bottom-negate-x",
        pcb_file,
    ])


def _export_jlcpcb_gerbers(
    pcb_file: Path,
    dir_jlcpcb: Path,
    copper_layers: str,
    prefix: str,
    is_panel: bool,
) -> None:
    """
    Gerbers matching jlcpcb.kibot.yml / panel_jlcpcb.kibot.yml:
      use_protel_extensions: true    (omit --no-protel-ext)
      gerber_precision: 4.6          --precision 6
      plot_sheet_reference: false    (omit --include-border-title)
      subtract_mask_from_silk: true  --subtract-soldermask
      use_gerber_x2_attributes: false --no-netlist (X2 off by default without --no-netlist)
      Non-panel: no paste layers.  Panel: include paste layers.
    """
    dir_gerber = dir_jlcpcb / "gerber"
    dir_gerber.mkdir(parents=True, exist_ok=True)
    if is_panel:
        layers = (
            f"{copper_layers},"
            "F.SilkS,B.SilkS,F.Mask,B.Mask,F.Paste,B.Paste,"
            "Edge.Cuts,User.Drawings,User.Comments,User.Eco1,User.Eco2"
        )
    else:
        layers = (
            f"{copper_layers},"
            "F.SilkS,B.SilkS,F.Mask,B.Mask,"
            "Edge.Cuts,User.Drawings,User.Comments,User.Eco1,User.Eco2"
        )
    run([
        "kicad-cli", "pcb", "export", "gerbers",
        "--output", str(dir_gerber) + "/",
        "--layers", layers,
        "--subtract-soldermask",
        pcb_file,
    ])
    rename_board_outputs(dir_gerber, pcb_file.stem, prefix)


def _export_jlcpcb_drill(pcb_file: Path, dir_jlcpcb: Path, prefix: str) -> None:
    """
    Drill matching jlcpcb.kibot.yml:
      pth_and_npth_single_file: false  --excellon-separate-th
      metric_units: true               --excellon-units mm
    """
    dir_drill = dir_jlcpcb / "drill"
    dir_drill.mkdir(parents=True, exist_ok=True)
    run([
        "kicad-cli", "pcb", "export", "drill",
        "--output", str(dir_drill) + "/",
        "--format", "excellon",
        "--excellon-units", "mm",
        "--excellon-separate-th",
        "--generate-map",
        pcb_file,
    ])
    rename_board_outputs(dir_drill, pcb_file.stem, prefix)


def _export_jlcpcb_pos(pcb_file: Path, dir_jlcpcb: Path, prefix: str) -> None:
    """
    CPL matching jlcpcb.kibot.yml JLCPCB_position output.
    kicad-cli outputs: Ref,Val,Package,PosX,PosY,Rot,Side
    JLCPCB expects:    Designator,Val,Package,Mid X,Mid Y,Rotation,Layer
    Post-processes the CSV to rename headers accordingly.
    """
    import csv

    raw = dir_jlcpcb / f"{prefix}_cpl_jlc_raw.csv"
    out = dir_jlcpcb / f"{prefix}_cpl_jlc.csv"
    run([
        "kicad-cli", "pcb", "export", "pos",
        "--output", raw,
        "--format", "csv",
        "--units", "mm",
        "--side", "both",
        pcb_file,
    ])
    header_map = {
        "Ref":   "Designator",
        "PosX":  "Mid X",
        "PosY":  "Mid Y",
        "Rot":   "Rotation",
        "Side":  "Layer",
    }
    with raw.open(newline="", encoding="utf-8") as fin, \
         out.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        new_fields = [header_map.get(f, f) for f in (reader.fieldnames or [])]
        writer = csv.DictWriter(fout, fieldnames=new_fields)
        writer.writeheader()
        for row in reader:
            writer.writerow({header_map.get(k, k): v for k, v in row.items()})
    raw.unlink()
    print(f"     {out}")


def _export_jlcpcb_bom(sch_file: Path, dir_jlcpcb: Path, prefix: str) -> None:
    """
    BOM matching jlcpcb.kibot.yml JLCPCB_bom output:
      columns: Value->Comment, References->Designator, Footprint, LCSC PN->LCSC Part #
    """
    run([
        "kicad-cli", "sch", "export", "bom",
        "--output", dir_jlcpcb / f"{prefix}_bom_jlc.csv",
        "--fields",
        "Reference,Value,Footprint,QUANTITY,DNP,Manufacturer,MPN,LCSC PN,Note",
        "--labels",
        "Designator,Comment,Footprint,Quantity,Populate,Manufacturer,MPN,LCSC Part #,Note",
        "--group-by", "Manufacturer,MPN",
        "--ref-range-delimiter", "", # Don't use a delimiter; list all designators in the Designator column.
        sch_file,
    ])


def export_jlcpcb(
    pcb_file: Path,
    sch_file: Path,
    out_base: Path,
    copper_layers: str,
    pcba_prefix: str,
    pcb_prefix: str,
    is_panel: bool,
) -> None:
    """
    JLCPCB-specific outputs matching jlcpcb.kibot.yml (non-panel) and
    panel_jlcpcb.kibot.yml (panel).

    Non-panel: gerbers + drill + CPL + BOM -> {pcba_prefix}_jlcpcb.zip
    Panel:     gerbers + drill             -> {pcba_prefix}_jlcpcb_panel.zip
    """
    section("JLCPCB Outputs")
    dir_jlcpcb = out_base / "special" / "jlcpcb"
    dir_jlcpcb.mkdir(parents=True, exist_ok=True)

    _export_jlcpcb_gerbers(pcb_file, dir_jlcpcb, copper_layers, pcb_prefix, is_panel)
    _export_jlcpcb_drill(pcb_file, dir_jlcpcb, pcb_prefix)
    if not is_panel:
        _export_jlcpcb_pos(pcb_file, dir_jlcpcb, pcba_prefix)
        _export_jlcpcb_bom(sch_file, dir_jlcpcb, pcba_prefix)

    # Zip gerber + drill into special/jlcpcb/ for direct JLCPCB upload
    fab_zip = dir_jlcpcb / f"{pcb_prefix}.zip"
    with zipfile.ZipFile(fab_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for subdir in ("gerber", "drill"):
            src = dir_jlcpcb / subdir
            if src.is_dir():
                for file in sorted(src.rglob("*")):
                    if file.is_file():
                        zf.write(file, file.relative_to(dir_jlcpcb))
    print(f"     {fab_zip}")


# ---------------------------------------------------------------------------
# Compress outputs
# ---------------------------------------------------------------------------

def zip_directory(source_dir: Path, output_zip: Path) -> None:
    """Recursively add all files under source_dir into output_zip."""
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(source_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(source_dir))
    print(f"     {output_zip}")


def zip_tree(root_dir: Path, output_zip: Path, exclude_suffix: str = ".zip") -> None:
    """Recursively add all files under root_dir, skipping zip files."""
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(root_dir.rglob("*")):
            if file.is_file() and file.suffix != exclude_suffix:
                zf.write(file, file.relative_to(root_dir))
    print(f"     {output_zip}")


def copy_impedance_xlsx(project_dir: Path, mfg_dir: Path) -> None:
    """Copy impedance_control.xlsx from the project directory into manufacturing/ if present."""
    src = project_dir / "impedance_control.xlsx"
    if src.is_file():
        section("Impedance Control Spreadsheet")
        mfg_dir.mkdir(parents=True, exist_ok=True)
        dest = mfg_dir / src.name
        shutil.copy2(src, dest)
        print(f"     {dest}")
    else:
        note("impedance_control.xlsx not found in project dir — skipping.")


def compress_manufacturing(out_base: Path, prefix: str) -> None:
    """kibot: zip_manufacturing — source: manufacturing/**"""
    section("ZIP: Manufacturing")
    mfg_dir = out_base / "manufacturing"
    zip_directory(mfg_dir, out_base / "manufacturing" / f"{prefix}-manufacturing.zip")


def compress_release(out_base: Path, prefix: str) -> None:
    """kibot: zip_release — source: **"""
    section("ZIP: Full Release")
    zip_tree(out_base, out_base / f"{prefix}.zip")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    pcb_file: Path = args.pcb_file.resolve()
    sch_file: Path = args.sch_file.resolve()
    is_panel: bool = args.panel

    if not pcb_file.is_file():
        print(f"ERROR: PCB file not found: {pcb_file}", file=sys.stderr)
        sys.exit(1)
    if not sch_file.is_file():
        print(f"ERROR: Schematic file not found: {sch_file}", file=sys.stderr)
        sys.exit(1)

    require_tool("kicad-cli")

    # Read text variables from the .kicad_pro file, then allow env var overrides.
    text_vars = read_project_text_vars(pcb_file)

    pcba_pn  = os.environ.get("PCBA_PN")  or text_vars.get("PCBA_PN",  "PROJ")
    pcba_rev = os.environ.get("PCBA_REV") or text_vars.get("PCBA_REV", "A")
    pcb_pn   = os.environ.get("PCB_PN")   or text_vars.get("PCB_PN",   pcba_pn)
    pcb_rev  = os.environ.get("PCB_REV")  or text_vars.get("PCB_REV",  pcba_rev)

    # Assembly files: PCBA_PN-PCBA_REV-<filename>
    # Fab files:      PCB_PN-PCB_REV-<filename>
    board_name = pcb_file.stem
    pcba_prefix = f"{pcba_pn}-{pcba_rev}-{board_name}"
    pcb_prefix  = f"{pcb_pn}-{pcb_rev}-{board_name}"

    project_dir: Path = args.project_dir.resolve() if args.project_dir else pcb_file.parent

    copper_layers = args.copper_layers or detect_copper_layers(pcb_file)
    print(f"PCBA prefix:      {pcba_prefix}")
    print(f"PCB prefix:       {pcb_prefix}")
    print(f"Copper layers:    {copper_layers}")
    print(f"Project dir:      {project_dir}")
    if is_panel:
        print("Mode:             panel")

    # Output root — exports/ subdirectory inside the project directory (overridable)
    out_base = args.output_dir.resolve() if args.output_dir else pcb_file.parent / "exports"
    if out_base.exists():
        shutil.rmtree(out_base)
    out_base.mkdir()

    dir_fab         = out_base / "manufacturing" / "fab"
    dir_gerber      = dir_fab / "gerber"
    dir_drill       = dir_fab / "drill"
    dir_assembly    = out_base / "manufacturing" / "assembly"
    dir_pnp         = dir_assembly / "pnp"
    dir_engineering = out_base / "engineering"
    dir_openpnp     = out_base / "special" / "openpnp"

    # --- Preflight ---
    # ERC and DRC is skipped for panel exports (panel has no separate schematic).
    if not is_panel:
        preflight_erc(sch_file, out_base, pcba_prefix)
        preflight_drc(pcb_file, out_base, pcb_prefix)

    # --- Fabrication (PCB_PN-PCB_REV prefix) ---
    export_gerbers(pcb_file, dir_gerber, copper_layers, pcb_prefix)
    export_drill(pcb_file, dir_drill, pcb_prefix)
    export_ipc_d356(pcb_file, dir_fab, pcb_prefix)
    export_drawing(pcb_file, dir_fab, pcb_prefix, copper_layers)

    # --- Assembly (PCBA_PN-PCBA_REV prefix) — skipped for panel ---
    if not is_panel:
        export_ibom(pcb_file, dir_assembly, pcba_prefix, args.ibom_script)
        export_positions(pcb_file, dir_pnp, pcba_prefix)
        export_bom(sch_file, dir_assembly, pcba_prefix)

    # --- Engineering — skipped for panel ---
    if not is_panel:
        export_schematic_pdf(sch_file, dir_engineering, pcba_prefix)
        export_3d_step(pcb_file, dir_engineering, pcb_prefix)

    # --- Specialized — skipped for panel ---
    if not is_panel:
        export_positions_openpnp(pcb_file, dir_openpnp, pcba_prefix)

    # --- JLCPCB specialized outputs ---
    if args.jlcpcb:
        export_jlcpcb(pcb_file, sch_file, out_base, copper_layers,
                      pcba_prefix, pcb_prefix, is_panel)

    # --- Impedance control spreadsheet (copied before zipping) ---
    copy_impedance_xlsx(project_dir, out_base / "manufacturing")

    # --- Compress ---
    compress_manufacturing(out_base, pcb_prefix)
    compress_release(out_base, pcba_prefix)

    section(f"Export complete: {pcba_prefix} / {pcb_prefix}")


if __name__ == "__main__":
    main()
