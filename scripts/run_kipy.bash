#!/bin/bash

###
# run_kipy.bash
#
# This script is used to run kipy in a docker container.
#
# Usage:
#   ./run_kipy.bash [args]
#   -i: Run the docker container as an interactive shell.
#   [args]: Arguments to pass to kipy/kipy_export_project.bash.
###
scripts_dir=$(dirname "$0")
kipy_dir=$(dirname $(dirname "$0"))/kipy
env_file=$kipy_dir/.env

container_kipy_dir="/kipy"
container_scripts_dir="/scripts"
container_kicad_libs_dir="/kicad-libs"
container_kicad_config_dir="/root/.config/kicad/10.0"
container_kicad_template_dir="/usr/share/kicad/template"

# Source .env file if it exists.
if [ -f $env_file ]; then
    echo "Pulling environment variables from $env_file."
    source $env_file
    # printenv
    # cat $env_file
else
    echo "No .env file found, creating one."
    touch $env_file
fi

# Check to see if KICAD_LIBS_DIR is set, read path from terminal if not.
if [ -z "$KICAD_LIBS_DIR" ]; then
    echo "Please enter the path to the KiCad libraries directory:"
    read kicad_libs_dir
    export KICAD_LIBS_DIR=$kicad_libs_dir
    echo "KICAD_LIBS_DIR=$KICAD_LIBS_DIR" >> $env_file
fi
echo -e "\tKICAD_LIBS_DIR: $KICAD_LIBS_DIR"

echo -e "\tMounting $kipy_dir to /kipy in the container."
echo -e "\tMounting $(pwd) to /projects in the container."
echo -e "\tMounting $KICAD_LIBS_DIR to /kicad-libs in the container."
echo -e "\tMounting $scripts_dir to /scripts in the container."

# Append received command line args into single string.
args=""
for arg in "$@"; do
    args="$args $arg"
done

# Set command based on whether -i flag is present
if [ "$1" == "-i" ]; then
    bash_command=(
        "bash"
        "-c"
        "bash $container_scripts_dir/install_kicad_libs.bash $container_kicad_libs_dir $container_kicad_config_dir $container_kicad_template_dir \
        && bash"
    )
    shift # Don't pass -i flag on to kipy_export_project with rest of args.
else
    bash_command=(
        "bash"
        "-c"
        "bash $container_scripts_dir/install_kicad_libs.bash $container_kicad_libs_dir $container_kicad_config_dir $container_kicad_template_dir \
        && bash $container_kipy_dir/kipy_export_project.bash $args"
    )
fi

echo "Bash command: ${bash_command[*]}"

docker run --rm -it \
    --workdir="/projects" \
    --volume="$KICAD_LIBS_DIR":"$container_kicad_libs_dir" \
    --volume=$(pwd):"/projects" \
    --volume=$kipy_dir:"$container_kipy_dir" \
    --volume=$scripts_dir:"$container_scripts_dir" \
    --env "KICAD_LIBS_DIR=$container_kicad_libs_dir" \
    --env "KICAD9_SYMBOL_DIR=/usr/share/kicad/symbols" \
    --env "KICAD9_FOOTPRINT_DIR=/usr/share/kicad/footprints" \
    --env "KICAD10_SYMBOL_DIR=/usr/share/kicad/symbols" \
    --env "KICAD10_FOOTPRINT_DIR=/usr/share/kicad/footprints" \
    coolnamesalltaken/pantsforbirds-kicad:latest \
    "${bash_command[@]}"
