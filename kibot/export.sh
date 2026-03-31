#!/usr/bin/env zsh
# ===========================================================================
# export.sh — KiCAD CLI export script
# Translated from config.kibot.yml
#
# Usage: ./export.sh <board.kicad_pcb> <schematic.kicad_sch>
#
# Environment variables (override defaults):
#   PCBA_PN   — Part number prefix (default: PROJ)
#   PCBA_REV  — Revision string   (default: A)
# ===========================================================================

setopt ERR_EXIT PIPE_FAIL

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
PCB_FILE="${1:?Usage: $0 <board.kicad_pcb> <schematic.kicad_sch>}"
SCH_FILE="${2:?Usage: $0 <board.kicad_pcb> <schematic.kicad_sch>}"

[[ -f "$PCB_FILE" ]] || { print "ERROR: PCB file not found: $PCB_FILE" >&2; exit 1 }
[[ -f "$SCH_FILE" ]] || { print "ERROR: Schematic file not found: $SCH_FILE" >&2; exit 1 }
command -v kicad-cli >/dev/null 2>&1 || { print "ERROR: kicad-cli not found in PATH" >&2; exit 1 }

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOARD_NAME="${PCB_FILE:t:r}"
PCBA_PN="${PCBA_PN:-PROJ}"
PCBA_REV="${PCBA_REV:-A}"
PREFIX="${PCBA_PN}-${PCBA_REV}_${BOARD_NAME}"

# Copper layers — extend for multi-layer boards (e.g. "F.Cu,In1.Cu,In2.Cu,B.Cu")
COPPER_LAYERS="F.Cu,B.Cu"

# Output root — same directory as the PCB file (mirrors KiBot's working dir)
OUT_BASE="$(dirname "$PCB_FILE")"

DIR_FAB="${OUT_BASE}/manufacturing/fab"
DIR_GERBER="${DIR_FAB}/gerber"
DIR_DRILL="${DIR_FAB}/drill"
DIR_ASSEMBLY="${OUT_BASE}/manufacturing/assembly"
DIR_PNP="${DIR_ASSEMBLY}/pnp"
DIR_ENGINEERING="${OUT_BASE}/engineering"
DIR_OPENPNP="${OUT_BASE}/special/openpnp"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
section() { print "\n=== $* ===" }
note()    { print "    NOTE: $*" }

# ---------------------------------------------------------------------------
# PREFLIGHT: ERC
# (kibot: preflight.erc: true)
# ---------------------------------------------------------------------------
section "Preflight: ERC"
mkdir -p "$OUT_BASE"
kicad-cli sch erc \
    --output "${OUT_BASE}/${PREFIX}-erc.txt" \
    "$SCH_FILE"

# ---------------------------------------------------------------------------
# PREFLIGHT: DRC
# (kibot: preflight.drc: true)
# --refill-zones     fill_zones: true
# --save-board       update_pcb_characteristics: true
# ---------------------------------------------------------------------------
section "Preflight: DRC"
kicad-cli pcb drc \
    --output "${OUT_BASE}/${PREFIX}-drc.txt" \
    --format report \
    --schematic-parity \
    --refill-zones \
    --save-board \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# FABRICATION: Gerbers
# (kibot: type: gerber)
#
# Option mapping:
#   subtract_mask_from_silk: true     --subtract-soldermask
#   use_gerber_x2_attributes: true    (X2 is on by default; no --no-x2)
#   use_gerber_net_attributes: false  --no-netlist
#   use_protel_extensions: false      --no-protel-ext
#   gerber_precision: 4.5             --precision 5  (5 decimal digits)
#   plot_sheet_reference: true        --include-border-title
#
# NOTE: line_width, tent_vias, and exclude_pads_from_silkscreen are board-
# level settings with no kicad-cli flag equivalents; configure them in the
# PCB file's plot settings before running this script.
# NOTE: create_gerber_job_file has no kicad-cli flag; KiCAD may generate
# the .gbrjob automatically depending on version.
# ---------------------------------------------------------------------------
section "Gerbers"
mkdir -p "$DIR_GERBER"
kicad-cli pcb export gerbers \
    --output "$DIR_GERBER/" \
    --layers "${COPPER_LAYERS},F.Mask,B.Mask,F.SilkS,B.SilkS,F.Fab,B.Fab,F.Paste,B.Paste,Edge.Cuts,User.Drawings,User.Comments" \
    --subtract-soldermask \
    --no-netlist \
    --no-protel-ext \
    --precision 5 \
    --include-border-title \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# FABRICATION: Drill — Excellon + PDF map
# (kibot: type: excellon, map: "pdf")
#
# pth_and_npth_single_file: true  omit --excellon-separate-th (default is merged)
# ---------------------------------------------------------------------------
section "Drill files (PDF map)"
mkdir -p "$DIR_DRILL"
kicad-cli pcb export drill \
    --output "$DIR_DRILL/" \
    --format excellon \
    --excellon-units mm \
    --generate-map \
    --map-format pdf \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# FABRICATION: Drill — Excellon + DXF map
# (kibot: type: excellon, map: "dxf")
# ---------------------------------------------------------------------------
section "Drill files (DXF map)"
kicad-cli pcb export drill \
    --output "$DIR_DRILL/" \
    --format excellon \
    --excellon-units mm \
    --generate-map \
    --map-format dxf \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# FABRICATION: IPC-D-356 Netlist
# (kibot: type: netlist, format: "ipc")
#
# NOTE: kicad-cli has no IPC-D-356 export command. The closest available
# format is IPC-2581 (kicad-cli pcb export ipc2581), which is a different
# standard. For a true IPC-D-356 file use KiCAD interactively:
#   File > Fabrication Outputs > IPC-D-356 Netlist
# or use the pcbnew Python scripting API.
# ---------------------------------------------------------------------------
section "IPC-D-356 Netlist"
note "Skipped — no kicad-cli equivalent. Export manually via pcbnew:"
note "  File > Fabrication Outputs > IPC-D-356 Netlist File"

# ---------------------------------------------------------------------------
# FABRICATION: Technical Drawing (multi-page PDF)
# (kibot: type: pcb_print)
#
# KiBot's pcb_print generates one PDF where each page has its own layer set.
# kicad-cli pcb export pdf --mode-multipage plots the same layers on every
# page, so instead we generate one PDF per page and merge them.
#
# Requires pdfunite (poppler-utils) or ghostscript (gs) to merge.
# ---------------------------------------------------------------------------
section "Technical Drawing PDF"
mkdir -p "$DIR_FAB"

# Page definitions: "title:layer,layer,..."
typeset -a _pages=(
    "primary-side:F.Cu,F.Mask,F.SilkS,F.Paste,Edge.Cuts,User.Drawings"
    "secondary-side:B.Cu,B.Mask,B.SilkS,B.Paste,Edge.Cuts"
    "primary-paste:F.Paste,Edge.Cuts"
    "secondary-paste:B.Paste,Edge.Cuts"
)
typeset -a _page_pdfs=()

for _p in "${_pages[@]}"; do
    _name="${_p%%:*}"
    _layers="${_p##*:}"
    _out="${DIR_FAB}/${PREFIX}-${_name}.pdf"
    kicad-cli pcb export pdf \
        --output "$_out" \
        --layers "$_layers" \
        --include-border-title \
        --mode-single \
        "$PCB_FILE"
    _page_pdfs+=("$_out")
done

# One page per copper layer (kibot: repeat_for_layer: F.Cu, repeat_layers: copper)
for _layer in ${(s:,:)COPPER_LAYERS}; do
    _safe="${_layer//./}"
    _out="${DIR_FAB}/${PREFIX}-copper-${_safe}.pdf"
    kicad-cli pcb export pdf \
        --output "$_out" \
        --layers "${_layer},Edge.Cuts" \
        --include-border-title \
        --mode-single \
        "$PCB_FILE"
    _page_pdfs+=("$_out")
done

_merged="${DIR_FAB}/${PREFIX}-fabrication.pdf"
if command -v pdfunite >/dev/null 2>&1; then
    pdfunite "${_page_pdfs[@]}" "$_merged"
    rm -f "${_page_pdfs[@]}"
    print "    Merged  ${_merged}"
elif command -v gs >/dev/null 2>&1; then
    gs -dBATCH -dNOPAUSE -q -sDEVICE=pdfwrite \
        -sOutputFile="$_merged" \
        "${_page_pdfs[@]}"
    rm -f "${_page_pdfs[@]}"
    print "    Merged (ghostscript)  ${_merged}"
else
    note "pdfunite/gs not found — individual page PDFs left in ${DIR_FAB}/"
    note "Install poppler-utils (brew install poppler) to auto-merge."
fi

# ---------------------------------------------------------------------------
# ASSEMBLY: Interactive HTML BOM
# (kibot: type: ibom)
#
# NOTE: ibom is not part of kicad-cli. It requires the InteractiveHtmlBom
# KiCAD plugin: https://github.com/openscopeproject/InteractiveHtmlBom
# Set IBOM_SCRIPT to the path of generate_interactive_bom.py to enable.
# ---------------------------------------------------------------------------
section "Interactive HTML BOM"
if [[ -n "${IBOM_SCRIPT:-}" && -f "$IBOM_SCRIPT" ]]; then
    mkdir -p "$DIR_ASSEMBLY"
    python3 "$IBOM_SCRIPT" \
        --dest-dir "$DIR_ASSEMBLY" \
        --no-browser \
        --include-tracks \
        --include-nets \
        --blacklist-empty-val \
        --dark-mode \
        --highlight-pin1 all \
        "$PCB_FILE"
else
    note "Skipped — set IBOM_SCRIPT=/path/to/generate_interactive_bom.py to enable."
fi

# ---------------------------------------------------------------------------
# ASSEMBLY: Pick and Place
# (kibot: type: position, format: ASCII, only_smd: false)
# ---------------------------------------------------------------------------
section "Pick and Place"
mkdir -p "$DIR_PNP"
kicad-cli pcb export pos \
    --output "${DIR_PNP}/${PREFIX}-pos.csv" \
    --format csv \
    --units mm \
    --side both \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# BOM: CSV
# (kibot: type: bom, group_fields: [Manufacturer, MPN])
# ---------------------------------------------------------------------------
section "BOM CSV"
mkdir -p "$DIR_ASSEMBLY"
kicad-cli sch export bom \
    --output "${DIR_ASSEMBLY}/${PREFIX}-bom.csv" \
    --fields "Reference,Value,Footprint,Datasheet,Quantity Per PCB,Footprint Populate,Standard Cost,Manufacturer,MPN,LCSC PN,Note" \
    --labels "Reference,Value,Footprint,Datasheet,Qty,Populate,Standard Cost,Manufacturer,MPN,LCSC PN,Note" \
    --group-by "Manufacturer,MPN" \
    "$SCH_FILE"

# ---------------------------------------------------------------------------
# ENGINEERING: Schematic PDF
# (kibot: type: pdf_sch_print)
# ---------------------------------------------------------------------------
section "Schematic PDF"
mkdir -p "$DIR_ENGINEERING"
kicad-cli sch export pdf \
    --output "${DIR_ENGINEERING}/${PREFIX}-schematic.pdf" \
    "$SCH_FILE"

# ---------------------------------------------------------------------------
# ENGINEERING: 3D Model (STEP)
# (kibot: type: export_3d)
# ---------------------------------------------------------------------------
section "3D Model (STEP)"
kicad-cli pcb export step \
    --output "${DIR_ENGINEERING}/${PREFIX}.step" \
    --include-silkscreen \
    --include-pads \
    --include-soldermask \
    --subst-models \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# SPECIALIZED: Pick and Place — OpenPNP
# (kibot: type: position, bottom_negative_x: true, include_virtual: true)
#
# --bottom-negate-x  bottom_negative_x: true
# NOTE: include_virtual has no kicad-cli equivalent; virtual footprints are
# included by default when --smd-only is not set.
# ---------------------------------------------------------------------------
section "Pick and Place (OpenPNP)"
mkdir -p "$DIR_OPENPNP"
kicad-cli pcb export pos \
    --output "${DIR_OPENPNP}/${PREFIX}-pos-openpnp.csv" \
    --format csv \
    --units mm \
    --side both \
    --bottom-negate-x \
    "$PCB_FILE"

# ---------------------------------------------------------------------------
# COMPRESS: Manufacturing ZIP
# (kibot: zip_manufacturing — source: manufacturing/**)
# ---------------------------------------------------------------------------
section "ZIP: Manufacturing"
(
    cd "${OUT_BASE}/manufacturing" || exit 1
    zip -r "../${PREFIX}-manufacturing.zip" .
)
print "     ${OUT_BASE}/${PREFIX}-manufacturing.zip"

# ---------------------------------------------------------------------------
# COMPRESS: Full Release ZIP
# (kibot: zip_release — source: **)
# ---------------------------------------------------------------------------
section "ZIP: Full Release"
(
    cd "$OUT_BASE" || exit 1
    zip -r "${PREFIX}.zip" . --exclude "*.zip"
)
print "     ${OUT_BASE}/${PREFIX}.zip"

section "Export complete: ${PREFIX}"
