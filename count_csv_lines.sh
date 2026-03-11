#!/bin/bash

# Script to count lines in AACR results CSV files for years 2004-2026

for year in {2004..2026}; do
    if [ "$year" -eq 2023 ]; then
        continue
    fi
    echo "Year ${year}: $(gcloud storage cat gs://aacr-abstracts-data-lake/aacr_results_${year}.csv | wc -l)"
done