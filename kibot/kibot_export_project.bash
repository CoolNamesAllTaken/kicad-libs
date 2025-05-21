#!/bin/bash

echo "====================="
echo kibot_export_project.bash $@

# projects_dir=$(dirname $0)
projects_dir=/projects
kibot_dir=/kibot
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

# Run custom KiBot configuration.
kibot -c $kibot_dir/config.kibot.yml -e $projects_dir/$project/$project.kicad_sch -d $exports_dir -g KICAD_LIBS_DIR=$KICAD_LIBS_DIR

# Run JLCPCB KiBot configuration.
if [ "$jlcpcb" = true ]; then
    echo "Running JLCPCB KiBot configuration"
    kibot -c $kibot_dir/jlcpcb.kibot.yml -e $projects_dir/$project/$project.kicad_sch -d $exports_dir -g KICAD_LIBS_DIR=$KICAD_LIBS_DIR
fi
# kibot -c $projects_dir/jlcpcb.kibot.yml -e $projects_dir/$project/$project.kicad_sch -d $exports_dir