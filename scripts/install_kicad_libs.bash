#!/bin/bash

# Script to update KiCad library tables with custom libraries
# Usage: ./update_kicad_libs.sh <path_to_kicad-libs> <path_to_table_files>

set -e  # Exit on any error

# Check if correct number of arguments provided
if [ $# -ne 2 ]; then
    echo "Usage: $0 <path_to_kicad-libs> <path_to_table_files>"
    echo "  <path_to_kicad-libs>: Path to folder containing lib_fp and lib_sch"
    echo "  <path_to_table_files>: Path to folder containing sym-lib-table and fp-lib-table"
    exit 1
fi

kicad_libs_path="$1"
table_files_path="$2"

echo "Installing KiCAD libraries from $kicad_libs_path to existing library tables in $table_files_path"

# Validate input paths
if [ ! -d "$kicad_libs_path" ]; then
    echo "Error: kicad-libs path does not exist: $kicad_libs_path"
    exit 1
fi

if [ ! -d "$table_files_path" ]; then
    echo "Error: table files path does not exist: $table_files_path"
    exit 1
fi

if [ ! -d "$kicad_libs_path/lib_fp" ]; then
    echo "Error: lib_fp folder not found in: $kicad_libs_path"
    exit 1
fi

if [ ! -d "$kicad_libs_path/lib_sch" ]; then
    echo "Error: lib_sch folder not found in: $kicad_libs_path"
    exit 1
fi

if [ ! -f "$table_files_path/sym-lib-table" ]; then
    echo "Error: sym-lib-table not found in: $table_files_path"
    exit 1
fi

if [ ! -f "$table_files_path/fp-lib-table" ]; then
    echo "Error: fp-lib-table not found in: $table_files_path"
    exit 1
fi

echo "Updating KiCad library tables..."
echo "Source libraries: $kicad_libs_path"
echo "Target tables: $table_files_path"
echo

# Create backup files
echo "Creating backup files..."
cp "$table_files_path/sym-lib-table" "$table_files_path/sym-lib-table.backup"
cp "$table_files_path/fp-lib-table" "$table_files_path/fp-lib-table.backup"

# Function to get absolute path
get_absolute_path() {
    echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
}

# Update sym-lib-table
echo "Processing symbol libraries..."
sym_table="$table_files_path/sym-lib-table"
sym_count=0

# Create temporary file for new sym-lib-table
temp_sym=$(mktemp)

# Copy everything except the closing parenthesis
head -n -1 "$sym_table" > "$temp_sym"

# Process .kicad_sym files in lib_sch
lib_sch_files=("$kicad_libs_path/lib_sch"/*.kicad_sym)
echo "  Found ${#lib_sch_files[@]} symbol libraries in $kicad_libs_path/lib_sch"
echo ${lib_sch_files[@]}
for sym_file in "${lib_sch_files[@]}"; do
    if [ -f "$sym_file" ]; then
        # Extract filename without extension
        filename=$(basename "$sym_file" .kicad_sym)
        # # Check if this library is already in the table
        if ! grep -q "\"$filename\"" "$sym_table"; then
            echo "  (lib (name \"$filename\")(type \"KiCad\")(uri \"$kicad_libs_path/lib_sch/$filename.kicad_sym\")(options \"\")(descr \"\"))" >> "$temp_sym"
            echo "  [ADDED         ] $filename"
        sym_count=$((sym_count+1))
        else
            echo "  [       SKIPPED] $filename"
        fi
    fi
done

# Add closing parenthesis
echo ")" >> "$temp_sym"
# cat $temp_sym

# Replace original file
mv "$temp_sym" "$sym_table"
# cat "$sym_table"

echo "Added $sym_count new symbol libraries"
echo

# Update fp-lib-table
echo "Processing footprint libraries..."
fp_table="$table_files_path/fp-lib-table"
fp_count=0

# Create temporary file for new fp-lib-table
temp_fp=$(mktemp)

# Copy everything except the closing parenthesis
head -n -1 "$fp_table" > "$temp_fp"

# Process .pretty folders in lib_fp
for pretty_dir in "$kicad_libs_path/lib_fp"/*.pretty; do
    if [ -d "$pretty_dir" ]; then
        # Extract directory name without .pretty extension
        dirname=$(basename "$pretty_dir" .pretty)
        
        # Check if this library is already in the table
        if ! grep -q "\"$dirname\"" "$fp_table"; then
            echo "  (lib (name \"$dirname\")(type \"KiCad\")(uri \"$kicad_libs_path/lib_fp/$dirname.pretty\")(options \"\")(descr \"\"))" >> "$temp_fp"
            echo "  [ADDED         ] $dirname"
            fp_count=$((fp_count+1))
        else
            echo "  [       SKIPPED] $dirname"
        fi
    fi
done

# Add closing parenthesis
echo ")" >> "$temp_fp"

# Replace original file
mv "$temp_fp" "$fp_table"
# cat "$fp_table"

echo "Added $fp_count new footprint libraries"
echo

echo "Library tables updated successfully!"
echo "Backup files created:"
echo "  $table_files_path/sym-lib-table.backup"
echo "  $table_files_path/fp-lib-table.backup"
echo
echo "Summary:"
echo "  Symbol libraries added: $sym_count"
echo "  Footprint libraries added: $fp_count"