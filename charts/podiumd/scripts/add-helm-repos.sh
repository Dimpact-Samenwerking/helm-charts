#!/usr/bin/env bash
# Adds all Helm repositories required by the podiumd chart.
# Run once before `helm dependency update` from charts/podiumd/.
set -euo pipefail

helm repo add bitnami         https://charts.bitnami.com/bitnami
helm repo add maykinmedia     https://maykinmedia.github.io/charts/
helm repo add wiremind         https://wiremind.github.io/wiremind-helm-charts
helm repo add dimpact          https://Dimpact-Samenwerking.github.io/helm-charts/
helm repo add kiss-elastic     https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic
helm repo add zac              https://infonl.github.io/dimpact-zaakafhandelcomponent/
helm repo add zgw-office-addin https://infonl.github.io/zgw-office-addin
helm repo add adfinis          https://charts.adfinis.com
helm repo add opstree          https://ot-container-kit.github.io/helm-charts/
helm repo add worth-nl         https://worth-nl.github.io/helm-charts

helm repo update
echo "All Helm repositories added and updated."
