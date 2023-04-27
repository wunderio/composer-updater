#!/bin/bash

# Used for adding $settings['updates_log_disabled'] to settings.php.

insert_lines_in_file() {
    local file_path="$1"
    local line_in_case="$2"
    local case_name="$3"
    local error_on_case_not_found="$4"

    # Find the case statement and insert the line inside the case block
    case_block=$(grep -n "case '${case_name}':" "$file_path")
    if [ -z "$case_block" ]; then
        if [ "$error_on_case_not_found" = true ]; then
            echo "Error: case statement not found."
            exit 1
        else
            return
        fi
    fi
    case_line=$(echo "$case_block" | cut -d ":" -f 1)
    case_indent=$(awk -v line="$case_line" '$1 ~ /^case$/ { print substr($0, 0, index($0, $2)-1); exit }' "$file_path")
    case_end=$(grep -n -m1 "^${case_indent}" "$file_path" | awk -F: '{print $1-1}')
    if [ -z "$case_end" ]; then
        echo "Error: end of case block not found."
        exit 1
    fi
    sed -i "${case_line} a\\
    ${line_in_case}
    " "$file_path"
}

# Check if the correct number of arguments is passed
if [ $# -ne 3 ]; then
    echo "Usage: $0 <file_path> <line_before_switch> <line_in_case>"
    exit 1
fi

# Check if the file exists
if [ ! -f "$1" ]; then
    echo "Error: file does not exist."
    exit 1
fi

# Find the switch statement
switch_line=$(grep -n "switch (\$env)" "$1" | cut -d ":" -f 1)
if [ -z "$switch_line" ]; then
    echo "Error: switch statement not found."
    exit 1
fi

# Insert the lines before the switch statement
sed -i "${switch_line}i\\
${2}
" "$1"

# Insert the second line after the cases
insert_lines_in_file "$1" "$3" "production" true #throw error if "production" is not found as it affects the PR code generation.
# Optinal but nice to have it "enabled" in Main/Master environments.
insert_lines_in_file "$1" "$3" "main" false
insert_lines_in_file "$1" "$3" "master" false
