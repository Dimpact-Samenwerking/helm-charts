Check `charts/podiumd/values.yaml` for UTF-8 BOM (bytes `0xEF 0xBB 0xBF`) that breaks YAML tooling. Strip if present.

```powershell
$path = "charts/podiumd/values.yaml"
$bytes = [System.IO.File]::ReadAllBytes($path)
if ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    [System.IO.File]::WriteAllBytes($path, $bytes[3..($bytes.Length-1)])
    Write-Host "BOM removed from $path"
} else {
    Write-Host "No BOM - OK"
}
```

If `$ARGUMENTS` is a path, check that file instead of the default.

Report result. If BOM was stripped, remind user the file was modified and should be re-staged.
