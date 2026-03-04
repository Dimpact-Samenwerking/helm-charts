#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "${0}")"

DRY_RUN=false
LIST_AFFECTED=false
CHOOSE=false
HIGHLIGHT_SOURCE=true
SEARCH_ROOT="."
FILE_DIVIDER="================================================================================"

print_usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} [options] [FILE ...]

Add/update openklant.settings.siteDomain in podiumd.yml files.
The value is derived from openklant.configuration.oidcUrl.

Options:
  --search-root DIR   Search for podiumd.yml files under DIR (default: .)
  --no-highlight-source  Do not highlight oidcUrl/siteDomain key-values in preview
  --dry-run           Show what would change (includes full openklant section preview)
  --list-affected     List affected files and show full openklant section preview
  --choose            Ask one-by-one whether each affected file should be updated
  -h, --help          Show this help message

Examples:
  ${SCRIPT_NAME} --dry-run --search-root applications/gemeenten
  ${SCRIPT_NAME} --dry-run --no-highlight-source
  ${SCRIPT_NAME} --list-affected
  ${SCRIPT_NAME} --choose --search-root applications/gemeenten
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

apply_site_domain_update() {
  local input_file="${1}"
  local site_domain="${2}"
  local output_file="${3}"

  awk -v new_site_domain="${site_domain}" '
    function indent_count(line, count) {
      count = 0
      while (substr(line, count + 1, 1) == " ") {
        count += 1
      }
      return count
    }
    function is_content(trimmed_line) {
      return (trimmed_line != "" && substr(trimmed_line, 1, 1) != "#")
    }
    function site_line(indent_spaces, prefix) {
      prefix = sprintf("%*s", indent_spaces, "")
      return prefix "siteDomain: \"" new_site_domain "\""
    }
    {
      line = $0
      trimmed = line
      sub(/^[ ]*/, "", trimmed)
      indent = indent_count(line)

      if (in_settings && is_content(trimmed) && indent <= settings_indent && trimmed !~ /^settings:[[:space:]]*$/) {
        if (!site_seen) {
          print site_line(settings_indent + 2)
          site_seen = 1
          changed = 1
        }
        in_settings = 0
      }

      if (in_openklant && is_content(trimmed) && indent <= openklant_indent && trimmed !~ /^openklant:[[:space:]]*$/) {
        if (in_settings && !site_seen) {
          print site_line(settings_indent + 2)
          site_seen = 1
          changed = 1
        }
        in_settings = 0
        in_openklant = 0
      }

      if (!in_openklant && trimmed ~ /^openklant:[[:space:]]*$/) {
        in_openklant = 1
        openklant_indent = indent
        print line
        next
      }

      if (in_openklant && !in_settings && trimmed ~ /^settings:[[:space:]]*$/ && indent > openklant_indent) {
        in_settings = 1
        settings_indent = indent
        site_seen = 0
        print line
        next
      }

      if (in_settings && trimmed ~ /^siteDomain:[[:space:]]*/ && indent == settings_indent + 2) {
        updated_site_line = site_line(indent)
        if (line != updated_site_line) {
          print updated_site_line
          changed = 1
        } else {
          print line
        }
        site_seen = 1
        next
      }

      print line
    }
    END {
      if (in_settings && !site_seen) {
        print site_line(settings_indent + 2)
      }
    }
  ' "${input_file}" > "${output_file}"
}

extract_domain_from_url() {
  local url="${1}"
  printf '%s' "${url}" | sed -E 's#^[A-Za-z][A-Za-z0-9+.-]*://##; s#/.*$##; s#^[^@]+@##; s#:[0-9]+$##'
}

show_openklant_section() {
  local file_path="${1}"
  local highlight="${2}"
  local oidc_url="${3}"
  local site_domain="${4}"

  awk -v highlight="${highlight}" -v oidc_url="${oidc_url}" -v site_domain="${site_domain}" '
    function indent_count(line, count) {
      count = 0
      while (substr(line, count + 1, 1) == " ") {
        count += 1
      }
      return count
    }
    function is_content(trimmed_line) {
      return (trimmed_line != "" && substr(trimmed_line, 1, 1) != "#")
    }
    {
      line = $0
      trimmed = line
      sub(/^[ ]*/, "", trimmed)
      indent = indent_count(line)

      if (start_line == 0 && trimmed ~ /^openklant:[[:space:]]*$/) {
        start_line = NR
        openklant_indent = indent
      } else if (start_line > 0 && end_line == 0 && is_content(trimmed) && indent <= openklant_indent) {
        end_line = NR - 1
      }

      lines[NR] = line
      last_line = NR
    }
    END {
      if (start_line == 0) {
        exit 1
      }
      if (end_line == 0) {
        end_line = last_line
      }
      for (i = start_line; i <= end_line; i++) {
        section_line = lines[i]
        if (highlight == "true" && index(section_line, "oidcUrl:") > 0 && index(section_line, oidc_url) > 0 && oidc_marked == 0) {
          print ">>> " section_line " <<<"
          oidc_marked = 1
        } else if (highlight == "true" && index(section_line, "siteDomain:") > 0 && index(section_line, site_domain) > 0 && site_marked == 0) {
          print ">>> " section_line " <<<"
          site_marked = 1
        } else {
          print section_line
        }
      }
    }
  ' "${file_path}"
}

render_preview() {
  local file_path="${1}"
  local site_domain="${2}"
  local oidc_url="${3}"
  local tmp_file

  tmp_file="$(mktemp)"
  apply_site_domain_update "${file_path}" "${site_domain}" "${tmp_file}"

  echo "Changed openklant section preview for ${file_path}:"
  if ! show_openklant_section "${tmp_file}" "${HIGHLIGHT_SOURCE}" "${oidc_url}" "${site_domain}"; then
    echo "  (Could not render openklant section in preview output)"
  fi
  rm -f "${tmp_file}"
}

discover_files() {
  local root_dir="${1}"
  find "${root_dir}" -type f -name "podiumd.yml" | sort
}

main() {
  require_command "yq"
  require_command "awk"
  require_command "sed"
  require_command "mktemp"
  require_command "find"
  require_command "sort"
  require_command "mv"

  local -a input_files=()
  local -a affected_files=()
  local -a affected_domains=()
  local arg=""
  local oidc_url=""
  local domain=""
  local current_site_domain=""
  local idx=0
  local answer=""
  local tmp_file=""

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
      --no-highlight-source)
        HIGHLIGHT_SOURCE=false
        shift
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      --list-affected)
        LIST_AFFECTED=true
        shift
        ;;
      --choose)
        CHOOSE=true
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

    oidc_url="$(yq eval -r '.openklant.configuration.oidcUrl // ""' "${file_path}")"
    if [[ -z "${oidc_url}" || "${oidc_url}" == "null" ]]; then
      continue
    fi

    domain="$(extract_domain_from_url "${oidc_url}")"
    if [[ -z "${domain}" ]]; then
      echo "Skipping file with unparsable oidcUrl: ${file_path}" >&2
      continue
    fi

    current_site_domain="$(yq eval -r '.openklant.settings.siteDomain // ""' "${file_path}")"
    if [[ "${current_site_domain}" == "${domain}" ]]; then
      continue
    fi

    affected_files[${#affected_files[@]}]="${file_path}"
    affected_domains[${#affected_domains[@]}]="${domain}"
  done

  if [[ "${#affected_files[@]}" -eq 0 ]]; then
    echo "No files need updates."
    exit 0
  fi

  if [[ "${LIST_AFFECTED}" == "true" || "${DRY_RUN}" == "true" ]]; then
    echo "Affected files (${#affected_files[@]}):"
    idx=0
    while [[ "${idx}" -lt "${#affected_files[@]}" ]]; do
      if [[ "${idx}" -gt 0 ]]; then
        echo "${FILE_DIVIDER}"
      fi
      echo "[$((idx + 1))] ${affected_files[${idx}]}"
      oidc_url="$(yq eval -r '.openklant.configuration.oidcUrl // ""' "${affected_files[${idx}]}")"
      render_preview "${affected_files[${idx}]}" "${affected_domains[${idx}]}" "${oidc_url}"
      echo ""
      idx=$((idx + 1))
    done
    if [[ "${DRY_RUN}" == "true" || "${LIST_AFFECTED}" == "true" ]]; then
      exit 0
    fi
  fi

  idx=0
  while [[ "${idx}" -lt "${#affected_files[@]}" ]]; do
    file_path="${affected_files[${idx}]}"
    domain="${affected_domains[${idx}]}"

    if [[ "${idx}" -gt 0 ]]; then
      echo "${FILE_DIVIDER}"
    fi

    if [[ "${CHOOSE}" == "true" ]]; then
      echo ""
      oidc_url="$(yq eval -r '.openklant.configuration.oidcUrl // ""' "${file_path}")"
      render_preview "${file_path}" "${domain}" "${oidc_url}"
      read -r -p "Update ${file_path}? [y/N]: " answer
      if [[ "${answer}" != "y" && "${answer}" != "Y" ]]; then
        echo "Skipped ${file_path}"
        idx=$((idx + 1))
        continue
      fi
    fi

    tmp_file="$(mktemp)"
    apply_site_domain_update "${file_path}" "${domain}" "${tmp_file}"
    mv "${tmp_file}" "${file_path}"
    echo "Updated ${file_path} -> openklant.settings.siteDomain=\"${domain}\""
    idx=$((idx + 1))
  done
}

main "${@}"
