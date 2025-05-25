#!/bin/bash

echo "====================="
echo kibot_export_project.bash $@

projects_dir=/projects
kibot_dir=/kibot
scripts_dir=/scripts
jlcpcb=false
project=""

# Parse command line arguments one by one
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            echo "Usage: run_kibot.sh [project_name] [-j|--jlcpcb]"
            echo "Available projects:"
            for project in "${project_list[@]}"; do
                echo "  $project"
            done
            exit 0
            ;;
        -j|--jlcpcb)
            echo "Will add exports for JLCPCB."
            jlcpcb=true
            shift
            ;;
        *)
            project=$1
            # Remove trailing slash from project name if it exists.
            project=${project%/}
            echo "Project: $project"
            shift
            ;;
    esac
done


# If project is empty string, exit.
if [ -z "$project" ]; then
    echo "Please enter a project name."
    exit 1
fi

# If project directory doesn't exist, exit.
if [ ! -d $projects_dir/$project ]; then
    echo "Project directory $projects_dir/$project does not exist."
    exit 1
fi

echo "Running KiBot for $project"
echo "Generating board outputs"

# Clear out the exports directory if it exists, make it if it doesn't.
exports_dir=$projects_dir/$project/exports
if [ -d $exports_dir ]; then
    rm -rf $exports_dir
else
    echo "Creating exports directory at $exports_dir"
    mkdir -p $exports_dir
fi

kibot_params=(
    "-e $projects_dir/$project/$project.kicad_sch"
    "-d $exports_dir"
    "-g KICAD_LIBS_DIR=$KICAD_LIBS_DIR"
    "-E PROJECT_DIR=$projects_dir/$project"
)

# Run custom KiBot configuration.
# echo ${kibot_params[@]}
kibot -c $kibot_dir/config.kibot.yml ${kibot_params[@]}

# Run JLCPCB KiBot configuration.
if [ "$jlcpcb" = true ]; then
    echo "Running JLCPCB KiBot configuration"
    kibot -c $kibot_dir/jlcpcb.kibot.yml ${kibot_params[@]}
fi

# If the project contains a panelize.json file, run kibot again with panelize.kibot.yml
if [ -f $projects_dir/$project/panel.json ]; then
    echo "Creating panelized design with KiBot"
    rm -rf $projects_dir/$project/panelized/*
    mkdir -p $projects_dir/$project/panelized

    # Create panelized KiCAD source files in the panelized directory with KiBot.
    kibot -c $kibot_dir/panelize.kibot.yml ${kibot_params[@]}

    kibot_panel_params=(
        # Use the original schematic and the panelized PCB to invoke KiBot.
        "-e $projects_dir/$project/panelized/$project-panel.kicad_pcb"
        "-b $projects_dir/$project/panelized/$project-panel.kicad_pcb"
        "-d $exports_dir/panel"
        "-g KICAD_LIBS_DIR=$KICAD_LIBS_DIR"
        "-E PROJECT_DIR=$projects_dir/$project/panelized"
    )

    echo "Exporting panelized design"
    kibot -c $kibot_dir/panel_config.kibot.yml ${kibot_panel_params[@]}

    if [ "$jlcpcb" = true ]; then
        echo "Running JLCPCB KiBot configuration for panelized design"
        kibot -c $kibot_dir/panel_jlcpcb.kibot.yml ${kibot_panel_params[@]}
    fi

fi