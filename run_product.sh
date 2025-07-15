#!/bin/bash

# Usage: ./run_product.sh [team_name] <product_shortname>
# Examples: 
#   ./run_product.sh kots                    # Run installers team, KOTS product
#   ./run_product.sh installers kots         # Run installers team, KOTS product
#   ./run_product.sh vendex vp    # Run vendex team, Vendor Portal product

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

# Function to show available products for a team
show_available_products() {
    local team=$1
    local config_file="config.$team.json"
    
    if [[ ! -f "$config_file" ]]; then
        echo "Error: Config file $config_file not found"
        return 1
    fi
    
    echo "Available products for $team team:"
    python3 -c "import sys, json; c=json.load(open('$config_file')); print('  ' + '\n  '.join(sorted([p['shortname'] for org in c['organizations'].values() for p in org['products'].values()])))"
}

# Parse arguments
if [ $# -eq 0 ]; then
    echo "Usage: $0 [team_name] <product_shortname>"
    echo "Examples:"
    echo "  $0 kots                    # Run installers team, KOTS product"
    echo "  $0 installers kots         # Run installers team, KOTS product"
    echo "  $0 vendex vp    # Run vendex team, Vendor Portal product"
    echo ""
    show_available_teams
    exit 1
fi

# Determine team and product
if [ $# -eq 1 ]; then
    # Only product specified, use default team
    TEAM=installers
    PRODUCT_SHORTNAME=$1
else
    # Both team and product specified
    TEAM=$1
    PRODUCT_SHORTNAME=$2
fi

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

echo "Running $TEAM team support digest for product: $PRODUCT_SHORTNAME"
python3 support_digest.py "$PRODUCT_SHORTNAME" 