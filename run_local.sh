#!/bin/bash

# Usage: ./run_local.sh [team_name]
# Examples: 
#   ./run_local.sh                    # Run installers team (default)
#   ./run_local.sh installers         # Run installers team
#   ./run_local.sh vendex  # Run vendex team

# Function to discover available teams from config files
discover_teams() {
    local teams=()
    for config_file in config.*.json; do
        if [[ -f "$config_file" ]]; then
            # Extract team name from config.team.json -> team
            local team=$(echo "$config_file" | sed 's/config\.\(.*\)\.json/\1/')
            # Exclude example files
            if [[ "$team" != "example" ]]; then
                teams+=("$team")
            fi
        fi
    done
    echo "${teams[@]}"
}

# Function to show available teams
show_available_teams() {
    echo "Available teams:"
    local teams=($(discover_teams))
    for team in "${teams[@]}"; do
        echo "  - $team"
    done
}

# Default team
TEAM=${1:-installers}

# Validate team exists
AVAILABLE_TEAMS=($(discover_teams))
TEAM_FOUND=false
for available_team in "${AVAILABLE_TEAMS[@]}"; do
    if [[ "$available_team" == "$TEAM" ]]; then
        TEAM_FOUND=true
        break
    fi
done

if [[ "$TEAM_FOUND" == false ]]; then
    echo "Error: Team '$TEAM' not found"
    show_available_teams
    exit 1
fi

# Require team-specific environment
if [ ! -f ".env.$TEAM" ]; then
    echo "Error: .env.$TEAM not found. Please create it from env.example."
    exit 1
fi
export $(cat .env.$TEAM | grep -v '^#' | xargs)
echo "Loaded environment from .env.$TEAM"

export CONFIG_FILE=config.$TEAM.json

echo "Running $TEAM team support digest (all products)..."
python3 support_digest.py 