<#
  One command puts a machine on the loop.

  Three things have to exist on every machine for a session to consult the
  board and file what it learns, and none of them travels with a repo or
  an account: the standing order in ~/.claude/CLAUDE.md, the pm-guidance
  bridge registered at user scope with the board's key, and the hooks in
  ~/.claude/settings.json that inject the rules at session start and
  refuse to let a session stop with an unfiled lesson. On 2026-09-04 a
  laptop had none of them, and nothing said so. This puts all three in
  place, and is safe to run again: the order is overwritten with the repo
  copy, the registration is replaced, and the hooks replace their own
  entries and touch nothing else.

  From the repo root:

      .\tools\bootstrap_guidance.ps1 -Key <PM_GUIDANCE_KEY>

  The key is GUIDANCE_API_KEY on the Built-By-Bean-Website Railway service.
#>
param([Parameter(Mandatory = $true)][string]$Key)

$repo = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $repo "tools\pm_guidance_mcp.py"
$order = Join-Path $repo "tools\STANDING_ORDER.md"
$installer = Join-Path $repo "tools\hooks\install.py"
$target = Join-Path $HOME ".claude\CLAUDE.md"

foreach ($f in @($bridge, $order, $installer)) {
    if (-not (Test-Path $f)) { throw "missing: $f" }
}

New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item $order $target -Force
Write-Host "standing order  -> $target"

# Replace rather than add beside: two registrations under one name is the
# kind of thing that works until the wrong one answers.
claude mcp remove pm-guidance -s user 2>$null | Out-Null
claude mcp add --scope user pm-guidance -e "PM_GUIDANCE_KEY=$Key" -- python $bridge
Write-Host "bridge          -> registered at user scope ($bridge)"

python $installer
Write-Host "hooks           -> ~/.claude/settings.json"

Write-Host ""
Write-Host "Done. Start a fresh Claude session; it opens with the house rules in it."
