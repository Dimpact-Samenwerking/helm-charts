#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "${0}")"
OLD_URL="http://api-proxy/"
NEW_URL="http://api-proxy.podiumd.svc.cluster.local/"
SEARCH_ROOT="."
DRY_RUN=false
FILE_DIVIDER="================================================================================"

print_usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} [options] [FILE ...]

Replace "${OLD_URL}" with "${NEW_URL}".

Options:
  --search-root DIR   Search for podiumd.yml files under DIR (default: .)
  --dry-run           Show what would be changed; do not write files
  -h, --help          Show this help message

Examples:
  ${SCRIPT_NAME} --dry-run --search-root applications/gemeenten
  ${SCRIPT_NAME} --search-root applications/gemeenten
  ${SCRIPT_NAME} applications/gemeenten/dimp/ontw/podiumd.yml
EOF
}

require_command() {
  local cmd="${1}"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Error: required command not found: ${cmd}" >&2
    exit 1
  fi
}

discover_files() {
  local root_dir="${1}"
  find "${root_dir}" -type f -name "podiumd.yml" | sort
}

count_old_url_occurrences() {
  local file_path="${1}"
  awk -v needle="${OLD_URL}" '
    {
      line = $0
      while (index(line, needle) > 0) {
        count += 1
        line = substr(line, index(line, needle) + length(needle))
      }
    }
    END {
      print count + 0
    }
  ' "${file_path}"
}

replace_in_file() {
  local file_path="${1}"
  local tmp_file=""

  tmp_file="$(mktemp)"
  sed 's#http://api-proxy/#http://api-proxy.podiumd.svc.cluster.local/#g' "${file_path}" > "${tmp_file}"
  mv "${tmp_file}" "${file_path}"
}

main() {
  require_command "find"
  require_command "sort"
  require_command "awk"
  require_command "sed"
  require_command "mktemp"
  require_command "mv"

  local -a input_files=()
  local -a affected_files=()
  local -a affected_counts=()
  local arg=""
  local file_path=""
  local count=0
  local idx=0
  local files_scanned=0
  local files_affected=0
  local total_replacements=0

  while [[ "${#}" -gt 0 ]]; do
    arg="${1}"
    case "${arg}" in
      --search-root)
        if [[ "${#}" -lt 2 ]]; then
          echo "Error: --search-root requires a directory argument." >&2
          exit 1
        fi
        SEARCH_ROOT="${2}"
        shift 2
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      -h|--help)
        print_usage
        exit 0
        ;;
      --*)
        echo "Error: unknown option: ${arg}" >&2
        print_usage
        exit 1
        ;;
      *)
        input_files[${#input_files[@]}]="${arg}"
        shift
        ;;
    esac
  done

  if [[ "${#input_files[@]}" -eq 0 ]]; then
    while IFS= read -r discovered_file; do
      input_files[${#input_files[@]}]="${discovered_file}"
    done < <(discover_files "${SEARCH_ROOT}")
  fi

  if [[ "${#input_files[@]}" -eq 0 ]]; then
    echo "No podiumd.yml files found."
    exit 0
  fi

  for file_path in "${input_files[@]}"; do
    if [[ ! -f "${file_path}" ]]; then
      echo "Skipping missing file: ${file_path}" >&2
      continue
    fi

    files_scanned=$((files_scanned + 1))
    count="$(count_old_url_occurrences "${file_path}")"
    if [[ "${count}" -gt 0 ]]; then
      affected_files[${#affected_files[@]}]="${file_path}"
      affected_counts[${#affected_counts[@]}]="${count}"
      files_affected=$((files_affected + 1))
      total_replacements=$((total_replacements + count))
    fi
  done

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "Dry-run report"
    echo "${FILE_DIVIDER}"
    echo "Files scanned: ${files_scanned}"
    echo "Files that would be updated: ${files_affected}"
    echo "Total replacements that would be made: ${total_replacements}"
    if [[ "${files_affected}" -gt 0 ]]; then
      echo "${FILE_DIVIDER}"
      idx=0
      while [[ "${idx}" -lt "${#affected_files[@]}" ]]; do
        echo "[$((idx + 1))] ${affected_files[${idx}]} (${affected_counts[${idx}]} replacements)"
        idx=$((idx + 1))
      done
    fi
    exit 0
  fi

  idx=0
  while [[ "${idx}" -lt "${#affected_files[@]}" ]]; do
    replace_in_file "${affected_files[${idx}]}"
    idx=$((idx + 1))
  done

  echo "Update report"
  echo "${FILE_DIVIDER}"
  echo "Files scanned: ${files_scanned}"
  echo "Files updated: ${files_affected}"
  echo "Total replacements made: ${total_replacements}"
  if [[ "${files_affected}" -gt 0 ]]; then
    echo "${FILE_DIVIDER}"
    idx=0
    while [[ "${idx}" -lt "${#affected_files[@]}" ]]; do
      echo "[$((idx + 1))] ${affected_files[${idx}]} (${affected_counts[${idx}]} replacements)"
      idx=$((idx + 1))
    done
  fi
}

main "${@}"
