#!/bin/bash

###
# run_kibot.bash
#
# This script is used to run KiBot in a docker container.
#
# Usage:
#   ./run_kibot.bash [args]
#   -i: Run the docker container as an interactive shell.
#   [args]: Arguments to pass to kibot_export_project.bash.
###
script_dir=$(dirname "$0")
env_file=$script_dir/.env

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

# Check to see if KICAD_SHARE_DIR is set, read path from terminal if not.
if [ -z "$KICAD_SHARE_DIR" ]; then
    echo "Please enter the path to the KiCad share directory:"
    read kicad_share_dir
    export KICAD_SHARE_DIR=$kicad_share_dir
    echo -e "\nKICAD_SHARE_DIR=$KICAD_SHARE_DIR" >> $env_file
fi
echo -e "\tKICAD_SHARE_DIR: $KICAD_SHARE_DIR"

# Check to see if KICAD_USER_DIR is set, read path from terminal if not.
if [ -z "$KICAD_USER_DIR" ]; then
    echo "Please enter the path to the KiCad user directory:"
    read kicad_user_dir
    export KICAD_USER_DIR=$kicad_user_dir
    echo -e "\nKICAD_USER_DIR=$KICAD_USER_DIR" >> $env_file
fi
echo -e "\tKICAD_USER_DIR: $KICAD_USER_DIR"

echo -e "\tMounting $script_dir to /kibot in the container."
echo -e "\tMounting $(pwd) to /projects in the container."

# # Convert paths to windows if necessary.
# host_kicad_libs_dir=$KICAD_LIBS_DIR
# host_kicad_share_dir=$KICAD_SHARE_DIR
# # Windows requires an extra leading slash on the path.
# path_prefix=""
# if [[ "$OS" == "Windows_NT" ]]; then
#     path_prefix="/"
#     host_kicad_libs_dir=$(cygpath.exe --windows $KICAD_LIBS_DIR)
#     echo "host_kicad_libs_dir=$host_kicad_libs_dir"
#     host_kicad_share_dir=$(cygpath.exe --windows "$KICAD_SHARE_DIR")
#     echo "host_kicad_share_dir=$host_kicad_share_dir"
# fi


# Append received command line args into single string.
args=""
for arg in "$@"; do
    args="$args $arg"
done

# Set command based on whether -i flag is present
if [ "$1" == "-i" ]; then
    shift # Don't pass -i flag on to kibot with rest of args.
    # Run kibot in a docker container
    MSYS_NO_PATHCONV=1 docker run --rm -it \
        --env KICAD_LIBS_DIR="/kicad-libs" \
        --env KICAD8_USER_DIR="/kicad-user" \
        --env KICAD8_TEMPLATE_DIR="/kicad-share/kicad/template" \
        --env KICAD8_SYMBOL_DIR="/kicad-share/kicad/symbols" \
        --env KICAD8_FOOTPRINT_DIR="/kicad-share/kicad/footprints" \
        --env KICAD8_3DMODEL_DIR="/kicad-share/kicad/3dmodels" \
        --volume="$KICAD_LIBS_DIR":"/kicad-libs" \
        --volume="$KICAD_USER_DIR":"/kicad-user" \
        --volume="$KICAD_SHARE_DIR/kicad":"/kicad-share/kicad" \
        --volume=$(pwd):"/projects" \
        --volume=$script_dir:"/kibot" \
        coolnamesalltaken/pantsforbirds-kibot:latest \
        bash
else
    # Run kibot in a docker container
    MSYS_NO_PATHCONV=1 docker run --rm -it \
        --env KICAD_LIBS_DIR="/kicad-libs" \
        --env KICAD8_USER_DIR="/kicad-user" \
        --env KICAD8_TEMPLATE_DIR="/kicad-share/kicad/template" \
        --env KICAD8_SYMBOL_DIR="/kicad-share/kicad/symbols" \
        --env KICAD8_FOOTPRINT_DIR="/kicad-share/kicad/footprints" \
        --env KICAD8_3DMODEL_DIR="/kicad-share/kicad/3dmodels" \
        --volume="$KICAD_LIBS_DIR":"/kicad-libs" \
        --volume="$KICAD_USER_DIR":"/kicad-user" \
        --volume="$KICAD_SHARE_DIR/kicad":"/kicad-share/kicad" \
        --volume=$(pwd):"/projects" \
        --volume=$script_dir:"/kibot" \
        coolnamesalltaken/pantsforbirds-kibot:latest \
        bash -c "cd /projects && bash /kibot/kibot_export_project.bash $args"
fi
