# Detects duplicate YAML map keys in values.yaml (silent data-loss bug).
# Run BEFORE git add (working tree), or AFTER git add (staged) using -Staged.
# False positives: list items sharing key names (value:, mountPath:) — ignore these.

param([switch]$Staged)

$script = @'
import re, sys
lines = sys.stdin.read().splitlines(keepends=True)
stack = []
scope_keys = {}
duplicates = []
for i, line in enumerate(lines, 1):
    stripped = line.lstrip()
    if stripped.startswith('#') or stripped.startswith('-'):
        continue
    m = re.match(r'^(\s*)([a-zA-Z0-9_\-][^:#\n]*?)\s*:', line)
    if not m:
        continue
    indent = len(m.group(1))
    key = m.group(2).strip()
    while stack and stack[-1][0] >= indent:
        stack.pop()
    scope_id = tuple(k for _,k in stack)
    if scope_id not in scope_keys:
        scope_keys[scope_id] = {}
    if key in scope_keys[scope_id]:
        parent = ' > '.join(scope_id) if scope_id else '(root)'
        duplicates.append(f'Line {i}: duplicate "{key}" under [{parent}] (first line {scope_keys[scope_id][key]})')
    else:
        scope_keys[scope_id][key] = i
    stack.append((indent, key))
if duplicates:
    print(f'FOUND {len(duplicates)} duplicate(s):')
    for d in duplicates: print(' ', d)
else:
    print('No duplicate keys found')
'@

if ($Staged) {
    git show :charts/podiumd/values.yaml | python -c $script
} else {
    Get-Content charts/podiumd/values.yaml -Raw | python -c $script
}
