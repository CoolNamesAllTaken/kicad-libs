#!/bin/bash

echo "====================="
echo "kipy/export_project.bash $@"

# Resolve the directory containing this script so export.py can be found
# regardless of the caller's working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_PY="$SCRIPT_DIR/export.py"

jlcpcb=false
panel_only=false
project=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            echo "Usage: export_project.bash <project_dir> [-j|--jlcpcb]"
            echo ""
            echo "  <project_dir>   Path to the KiCAD project directory."
            echo "                  Must contain <name>.kicad_pcb and <name>.kicad_sch."
            echo "  -j|--jlcpcb     (not yet implemented in kipy — flag accepted but ignored)
  -p|--panel-only Skip the main export and run only panelization (requires panel.json)."
            echo ""
            echo "Environment variables forwarded to export.py:"
            echo "  PCBA_PN     Part-number prefix    (default: PROJ)"
            echo "  PCBA_REV    Revision string        (default: A)"
            echo "  IBOM_SCRIPT Path to generate_interactive_bom.py"
            echo "  COPPER_LAYERS  Comma-separated layer list (default: F.Cu,B.Cu)"
            echo ""
            echo "Panelization:"
            echo "  If <project_dir>/panel.json exists, the panel is built with the"
            echo "  kikit CLI (must be available on PATH) and then exported with export.py."
            exit 0
            ;;
        -j|--jlcpcb)
            echo "NOTE: JLCPCB export is not yet implemented in kipy — flag ignored."
            jlcpcb=true
            shift
            ;;
        -p|--panel-only)
            panel_only=true
            shift
            ;;
        *)
            project=$1
            # Remove trailing slash if present.
            project=${project%/}
            echo "Project: $project"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------

if [ -z "$project" ]; then
    echo "ERROR: Please provide a project directory path."
    exit 1
fi

if [ ! -d "$project" ]; then
    echo "ERROR: Project directory '$project' does not exist."
    exit 1
fi

project_name=$(basename "$project")
project_abs=$(cd "$project" && pwd)

# Locate PCB and schematic files (prefer name-matching the directory).
pcb_file="$project_abs/$project_name.kicad_pcb"
sch_file="$project_abs/$project_name.kicad_sch"

if [ ! -f "$pcb_file" ]; then
    pcb_file=$(find "$project_abs" -maxdepth 1 -name "*.kicad_pcb" | head -1)
fi
if [ ! -f "$sch_file" ]; then
    sch_file=$(find "$project_abs" -maxdepth 1 -name "*.kicad_sch" | head -1)
fi

if [ ! -f "$pcb_file" ]; then
    echo "ERROR: No .kicad_pcb file found in '$project_abs'."
    exit 1
fi
if [ ! -f "$sch_file" ]; then
    echo "ERROR: No .kicad_sch file found in '$project_abs'."
    exit 1
fi

echo "PCB:        $pcb_file"
echo "Schematic:  $sch_file"

# ---------------------------------------------------------------------------
# Build export.py argument list
# ---------------------------------------------------------------------------

export_py_args=()
if [ -n "$COPPER_LAYERS" ]; then
    export_py_args+=("--copper-layers" "$COPPER_LAYERS")
fi
if [ -n "$IBOM_SCRIPT" ]; then
    export_py_args+=("--ibom-script" "$IBOM_SCRIPT")
fi

# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

if [ "$panel_only" = false ]; then
    echo ""
    echo "Running Python export for $project_name"
    python3 "$EXPORT_PY" "$pcb_file" "$sch_file" "${export_py_args[@]}"
fi

# ---------------------------------------------------------------------------
# Panelization via KiKit Docker
# ---------------------------------------------------------------------------

panel_json="$project_abs/panel.json"

if [ -f "$panel_json" ]; then
    echo ""
    echo "panel.json found — creating panelized design with kikit"

    panel_dir="$project_abs/panelized"
    rm -rf "$panel_dir"
    mkdir -p "$panel_dir"

    panel_pcb_host="$panel_dir/$project_name-panel.kicad_pcb"

    kikit panelize \
        --preset "$panel_json" \
        "$project_abs/$project_name.kicad_pcb" \
        "$panel_pcb_host"

    if [ ! -f "$panel_pcb_host" ]; then
        echo "ERROR: KiKit did not produce the expected panel PCB at $panel_pcb_host"
        exit 1
    fi

    echo ""
    echo "Exporting panelized design"

    # Export the panel using the original schematic (the panel has no separate
    # schematic; ERC is skipped by export.py when the sch path is the same as
    # the main project's).
    python3 "$EXPORT_PY" "$panel_pcb_host" "$sch_file" "${export_py_args[@]}"
fi

echo ""
echo "====================="
echo "export_project.bash complete: $project_name"
