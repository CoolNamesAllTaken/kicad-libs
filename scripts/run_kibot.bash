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
scripts_dir=$(dirname "$0")
kibot_dir=$(dirname $(dirname "$0"))/kibot
env_file=$kibot_dir/.env

container_kibot_dir="/kibot"
container_scripts_dir="/scripts"
container_kicad_libs_dir="/kicad-libs"
container_kicad_config_dir="/usr/share/kicad/template"
# Additional config dirs at /home/kicad/.config/kicad/9.0 and /root/.config/kicad/9.0 but these aren't used.

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

echo -e "\tMounting $kibot_dir to /kibot in the container."
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
        "bash $container_scripts_dir/install_kicad_libs.bash $container_kicad_libs_dir $container_kicad_config_dir \
        && bash"
    )
    shift # Don't pass -i flag on to kibot with rest of args.
else
    bash_command=(
        "bash" 
        "-c" 
        "bash $container_scripts_dir/install_kicad_libs.bash $container_kicad_libs_dir $container_kicad_config_dir \
        && bash $container_kibot_dir/kibot_export_project.bash $args"
    )
fi

echo "Bash command: ${bash_command[*]}"

docker run --rm -it \
    --volume="$KICAD_LIBS_DIR":"$container_kicad_libs_dir" \
    --volume=$(pwd):"/projects" \
    --volume=$kibot_dir:"$container_kibot_dir" \
    --volume=$scripts_dir:"$container_scripts_dir" \
    --env "KICAD_LIBS_DIR=$container_kicad_libs_dir" \
    --env "KICAD_CONFIG_DIR=$container_kicad_user_config_dir" \
    coolnamesalltaken/pantsforbirds-kibot:latest \
    "${bash_command[@]}"