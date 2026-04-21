#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "${0}")"
DRY_RUN=false
LIST_AFFECTED=false
CHOOSE=false
SEARCH_ROOT="."
FILE_DIVIDER="================================================================================"

# Known environment prefixes — extend this list if new environments are added.
# A URL hostname whose first label starts with one of these prefixes (before the
# first dash) is recognised as a non-production environment.
ENV_PREFIXES="test acc dev ota ont ontw tst pre stg"

print_usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} [options] [FILE ...]

Set zgw-office-addin.common.appEnv in podiumd.yml files.
The appEnv value is derived from the first api_root URL found in the file.
The first label of the URL hostname, before the first dash, is used as the
environment name if it matches a known prefix (${ENV_PREFIXES}).
Otherwise the value defaults to "production".

Examples of URL-to-env mapping:
  https://test-openzaak.assen.nl/zaken/api/v1/   ->  test
  https://acc-keycloak-admin.groningen.nl        ->  acc
  https://podiumd-logs.enschede.nl               ->  production  (no known env prefix)
  https://openzaak.assen.nl/zaken/api/v1/        ->  production  (no dash)

Options:
  --search-root DIR   Search for podiumd.yml files under DIR (default: .)
  --dry-run           Show what would change; do not write files
  --list-affected     List affected files and show appEnv change preview
  --choose            Ask one-by-one whether each affected file should be updated
  -h, --help          Show this help message

Examples:
  ${SCRIPT_NAME} --dry-run --search-root applications/gemeenten
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

discover_files() {
  local root_dir="${1}"
  find "${root_dir}" -type f -name "podiumd.yml" | sort
}

# Extract the first non-commented api_root URL from a YAML file.
# Only lines where api_root: is the key itself (not inside a comment) are matched.
extract_api_root_url() {
  local file_path="${1}"
  awk '
    {
      trimmed = $0
      sub(/^[ \t]*/, "", trimmed)
      if (substr(trimmed, 1, 1) == "#") next
      if (trimmed ~ /^api_root:[[:space:]]/) {
        val = trimmed
        sub(/^api_root:[[:space:]]*/, "", val)
        sub(/[[:space:]#].*$/, "", val)
        if (val != "" && val != "~" && val != "null") {
          print val
          exit
        }
      }
    }
  ' "${file_path}"
}

# Determine the appEnv value from a URL.
# Returns the prefix before the first dash in the first hostname label if it is
# a known environment prefix; otherwise returns "production".
determine_app_env() {
  local url="${1}"
  local hostname first_label prefix env_prefix

  # Strip scheme (https://, http://, ...)
  hostname="${url#*://}"
  # Strip path and everything after
  hostname="${hostname%%/*}"
  # Strip port
  hostname="${hostname%%:*}"
  # Strip userinfo (user:pass@)
  hostname="${hostname##*@}"

  # Use only the first DNS label (before the first dot)
  first_label="${hostname%%.*}"

  # If the first label contains a dash, check whether the prefix is a known env name
  if [[ "${first_label}" == *"-"* ]]; then
    prefix="${first_label%%-*}"
    for env_prefix in ${ENV_PREFIXES}; do
      if [[ "${prefix}" == "${env_prefix}" ]]; then
        printf '%s' "${prefix}"
        return
      fi
    done
  fi

  printf '%s' "production"
}

# Rewrite zgw-office-addin.common.appEnv in input_file, writing result to output_file.
# If common: or appEnv: are absent inside zgw-office-addin:, they are inserted.
apply_app_env_update() {
  local input_file="${1}"
  local new_app_env="${2}"
  local output_file="${3}"

  awk -v new_env="${new_app_env}" '
    function indent_count(line,    count) {
      count = 0
      while (substr(line, count + 1, 1) == " ") count++
      return count
    }
    function is_content(trimmed) {
      return (trimmed != "" && substr(trimmed, 1, 1) != "#")
    }
    function make_env_line(spaces,    prefix) {
      prefix = sprintf("%*s", spaces, "")
      return prefix "appEnv: \"" new_env "\""
    }
    {
      line = $0
      trimmed = line
      sub(/^[ ]*/, "", trimmed)
      indent = indent_count(line)

      # --- Leaving common: section (still inside zgw-office-addin:) ---
      if (in_zgw && in_common && is_content(trimmed) && indent <= common_indent && trimmed !~ /^common:[[:space:]]*$/) {
        if (!env_seen) {
          print make_env_line(common_indent + 2)
          env_seen = 1
        }
        in_common = 0
      }

      # --- Leaving zgw-office-addin: section ---
      if (in_zgw && is_content(trimmed) && indent <= zgw_indent && trimmed !~ /^zgw-office-addin:[[:space:]]*$/) {
        if (!in_common && !env_seen) {
          # common: was never encountered — insert it with appEnv:
          print sprintf("%*s", zgw_indent + 2, "") "common:"
          print make_env_line(zgw_indent + 4)
        }
        in_common = 0
        in_zgw = 0
      }

      # --- Entering zgw-office-addin: ---
      if (!in_zgw && trimmed ~ /^zgw-office-addin:[[:space:]]*$/) {
        in_zgw = 1
        zgw_indent = indent
        env_seen = 0
        print line
        next
      }

      # --- Entering common: inside zgw-office-addin: ---
      if (in_zgw && !in_common && trimmed ~ /^common:[[:space:]]*$/ && indent > zgw_indent) {
        in_common = 1
        common_indent = indent
        env_seen = 0
        print line
        next
      }

      # --- Updating existing appEnv: inside common: ---
      if (in_common && trimmed ~ /^appEnv:[[:space:]]/ && indent == common_indent + 2) {
        new_line = make_env_line(indent)
        if (line != new_line) {
          print new_line
        } else {
          print line
        }
        env_seen = 1
        next
      }

      print line
    }
    END {
      # Handle files that end while still inside a section
      if (in_common && !env_seen) {
        print make_env_line(common_indent + 2)
      } else if (in_zgw && !in_common) {
        print sprintf("%*s", zgw_indent + 2, "") "common:"
        print make_env_line(zgw_indent + 4)
      }
    }
  ' "${input_file}" > "${output_file}"
}

# Show the zgw-office-addin: section from a file, highlighting the appEnv: line.
show_zgw_section() {
  local file_path="${1}"
  local new_env="${2}"

  awk -v new_env="${new_env}" '
    function indent_count(line,    count) {
      count = 0
      while (substr(line, count + 1, 1) == " ") count++
      return count
    }
    function is_content(trimmed) {
      return (trimmed != "" && substr(trimmed, 1, 1) != "#")
    }
    {
      line = $0
      trimmed = line
      sub(/^[ ]*/, "", trimmed)
      indent = indent_count(line)

      if (start_line == 0 && trimmed ~ /^zgw-office-addin:[[:space:]]*$/) {
        start_line = NR
        zgw_indent = indent
      } else if (start_line > 0 && end_line == 0 && is_content(trimmed) && indent <= zgw_indent) {
        end_line = NR - 1
      }
      lines[NR] = line
      last_line = NR
    }
    END {
      if (start_line == 0) exit 1
      if (end_line == 0) end_line = last_line
      for (i = start_line; i <= end_line; i++) {
        section_line = lines[i]
        if (index(section_line, "appEnv:") > 0 && index(section_line, new_env) > 0 && env_marked == 0) {
          print ">>> " section_line " <<<"
          env_marked = 1
        } else {
          print section_line
        }
      }
    }
  ' "${file_path}"
}

render_preview() {
  local file_path="${1}"
  local new_env="${2}"
  local tmp_file

  tmp_file="$(mktemp)"
  apply_app_env_update "${file_path}" "${new_env}" "${tmp_file}"

  echo "  Changed zgw-office-addin section preview for ${file_path}:"
  if ! show_zgw_section "${tmp_file}" "${new_env}"; then
    echo "  (Could not render zgw-office-addin section in preview output)"
  fi
  rm -f "${tmp_file}"
}

main() {
  require_command "yq"
  require_command "awk"
  require_command "grep"
  require_command "mktemp"
  require_command "find"
  require_command "sort"
  require_command "mv"

  local -a input_files=()
  local -a affected_files=()
  local -a affected_envs=()
  local -a affected_current_envs=()
  local arg=""
  local api_root_url=""
  local new_env=""
  local current_env=""
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

    # Skip files that don't reference zgw-office-addin at all
    if ! grep -qE '^[[:space:]]*zgw-office-addin:' "${file_path}"; then
      continue
    fi

    api_root_url="$(extract_api_root_url "${file_path}")"
    if [[ -z "${api_root_url}" ]]; then
      echo "Skipping file with no api_root URL: ${file_path}" >&2
      continue
    fi

    new_env="$(determine_app_env "${api_root_url}")"

    # Read current value; treat absent/null as "production" (the chart default)
    current_env="$(yq eval -r '."zgw-office-addin".common.appEnv // ""' "${file_path}")"
    if [[ -z "${current_env}" || "${current_env}" == "null" ]]; then
      current_env="production"
    fi

    if [[ "${current_env}" == "${new_env}" ]]; then
      continue
    fi

    affected_files[${#affected_files[@]}]="${file_path}"
    affected_envs[${#affected_envs[@]}]="${new_env}"
    affected_current_envs[${#affected_current_envs[@]}]="${current_env}"
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
      echo "[$((idx + 1))] ${affected_files[${idx}]}  (${affected_current_envs[${idx}]} -> ${affected_envs[${idx}]})"
      render_preview "${affected_files[${idx}]}" "${affected_envs[${idx}]}"
      echo ""
      idx=$((idx + 1))
    done
    exit 0
  fi

  idx=0
  while [[ "${idx}" -lt "${#affected_files[@]}" ]]; do
    file_path="${affected_files[${idx}]}"
    new_env="${affected_envs[${idx}]}"

    if [[ "${idx}" -gt 0 ]]; then
      echo "${FILE_DIVIDER}"
    fi

    if [[ "${CHOOSE}" == "true" ]]; then
      echo ""
      render_preview "${file_path}" "${new_env}"
      read -r -p "Update ${file_path}? [y/N]: " answer
      if [[ "${answer}" != "y" && "${answer}" != "Y" ]]; then
        echo "Skipped ${file_path}"
        idx=$((idx + 1))
        continue
      fi
    fi

    tmp_file="$(mktemp)"
    apply_app_env_update "${file_path}" "${new_env}" "${tmp_file}"
    mv "${tmp_file}" "${file_path}"
    echo "Updated ${file_path} -> zgw-office-addin.common.appEnv=\"${new_env}\""
    idx=$((idx + 1))
  done
}

main "${@}"
