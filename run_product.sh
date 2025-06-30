#!/bin/bash

# Usage: ./run_product.sh <product_shortname>
# Example: ./run_product.sh kots

if [ $# -eq 0 ]; then
    echo "Usage: $0 <product_shortname>"
    echo "Available shortnames:"
    python3 -c 'import sys, json; c=json.load(open("config.json")); print("  " + "\n  ".join(sorted([p["shortname"] for org in c["organizations"].values() for p in org["products"].values()])))'
    exit 1
fi

PRODUCT_SHORTNAME=$1

python3 support_digest.py "$PRODUCT_SHORTNAME" 