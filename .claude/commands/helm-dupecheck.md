Scan charts/podiumd/values.yaml for duplicate YAML keys that silently overwrite earlier values.

Run the appropriate variant based on whether changes are staged or not.

**Working tree variant** (before `git add`):

```powershell
$script = @'
import re
lines = open(r'charts/podiumd/values.yaml', encoding='utf-8').readlines()
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
$script | python
```

**Staged variant** (after `git add`, before `git commit`):

```powershell
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
git show :charts/podiumd/values.yaml | python -c $script
```

After running, report any duplicates found. Hits inside YAML sequences (list items with shared key names like `value:` or `mountPath:`) are false positives — ignore them.
