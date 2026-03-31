#!/usr/bin/env python3
# ===========================================================================
# export.py — KiCAD Python export script
# Translated from config.kibot.yml
#
# Usage:
#   python3 export.py <board.kicad_pcb> <schematic.kicad_sch>
#
# Environment variables (override defaults):
#   PCBA_PN   — Part number prefix (default: PROJ)
#   PCBA_REV  — Revision string   (default: A)
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

def export_gerbers(pcb_file: Path, dir_gerber: Path, copper_layers: str) -> None:
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
        "--no-netlist",
        "--no-protel-ext",
        "--precision", "5",
        "--include-border-title",
        pcb_file,
    ])


def export_drill(pcb_file: Path, dir_drill: Path) -> None:
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

    dir_assembly.mkdir(parents=True, exist_ok=True)
    os.environ['INTERACTIVE_HTML_BOM_NO_DISPLAY'] = '' # Tell interactive html bom we have no display.
    run([
        Path("/usr/local/bin/generate_interactive_bom"),
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
        "Reference,Value,Footprint,Datasheet,"
        "Quantity Per PCB,Footprint Populate,Standard Cost,"
        "Manufacturer,MPN,LCSC PN,Note",
        "--labels",
        "Reference,Value,Footprint,Datasheet,"
        "Qty,Populate,Standard Cost,"
        "Manufacturer,MPN,LCSC PN,Note",
        "--group-by", "Manufacturer,MPN",
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


def compress_manufacturing(out_base: Path, prefix: str) -> None:
    """kibot: zip_manufacturing — source: manufacturing/**"""
    section("ZIP: Manufacturing")
    mfg_dir = out_base / "manufacturing"
    zip_directory(mfg_dir, out_base / f"{prefix}-manufacturing.zip")


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

    if not pcb_file.is_file():
        print(f"ERROR: PCB file not found: {pcb_file}", file=sys.stderr)
        sys.exit(1)
    if not sch_file.is_file():
        print(f"ERROR: Schematic file not found: {sch_file}", file=sys.stderr)
        sys.exit(1)

    require_tool("kicad-cli")

    board_name = pcb_file.stem
    pcba_pn = os.environ.get("PCBA_PN", "PROJ")
    pcba_rev = os.environ.get("PCBA_REV", "A")
    prefix = f"{pcba_pn}-{pcba_rev}_{board_name}"
    copper_layers = detect_copper_layers(pcb_file)
    print(f"Detected copper layers: {copper_layers}")

    # Output root — exports/ subdirectory inside the project directory
    out_base = pcb_file.parent / "exports"
    if out_base.exists():
        shutil.rmtree(out_base)
    out_base.mkdir()

    dir_fab       = out_base / "manufacturing" / "fab"
    dir_gerber    = dir_fab / "gerber"
    dir_drill     = dir_fab / "drill"
    dir_assembly  = out_base / "manufacturing" / "assembly"
    dir_pnp       = dir_assembly / "pnp"
    dir_engineering = out_base / "engineering"
    dir_openpnp   = out_base / "special" / "openpnp"

    # --- Preflight ---
    preflight_erc(sch_file, out_base, prefix)
    preflight_drc(pcb_file, out_base, prefix)

    # --- Fabrication ---
    export_gerbers(pcb_file, dir_gerber, copper_layers)
    export_drill(pcb_file, dir_drill)
    export_ipc_d356(pcb_file, dir_fab, prefix)
    export_drawing(pcb_file, dir_fab, prefix, copper_layers)

    # --- Assembly ---
    export_ibom(pcb_file, dir_assembly, prefix)
    export_positions(pcb_file, dir_pnp, prefix)

    # --- BOM ---
    export_bom(sch_file, dir_assembly, prefix)

    # --- Engineering ---
    export_schematic_pdf(sch_file, dir_engineering, prefix)
    export_3d_step(pcb_file, dir_engineering, prefix)

    # --- Specialized ---
    export_positions_openpnp(pcb_file, dir_openpnp, prefix)

    # --- Compress ---
    compress_manufacturing(out_base, prefix)
    compress_release(out_base, prefix)

    section(f"Export complete: {prefix}")


if __name__ == "__main__":
    main()
