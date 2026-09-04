<#
  One command puts a machine on the loop.

  Two things have to exist on every machine for a session to consult the
  board and file what it learns, and neither travels with a repo or an
  account: the standing order in ~/.claude/CLAUDE.md, and the pm-guidance
  bridge registered at user scope with the board's key. On 2026-09-04 a
  laptop had neither, and nothing said so. This puts both in place, and
  is safe to run again: the order is overwritten with the repo copy and
  the registration is replaced.

  From the repo root:

      .\tools\bootstrap_guidance.ps1 -Key <PM_GUIDANCE_KEY>

  The key is GUIDANCE_API_KEY on the Built-By-Bean-Website Railway service.
#>
param([Parameter(Mandatory = $true)][string]$Key)

$repo = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $repo "tools\pm_guidance_mcp.py"
$order = Join-Path $repo "tools\STANDING_ORDER.md"
$target = Join-Path $HOME ".claude\CLAUDE.md"

if (-not (Test-Path $bridge)) { throw "bridge not found at $bridge" }
if (-not (Test-Path $order)) { throw "standing order not found at $order" }

New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item $order $target -Force
Write-Host "standing order  -> $target"

# Replace rather than add beside: two registrations under one name is the
# kind of thing that works until the wrong one answers.
claude mcp remove pm-guidance -s user 2>$null | Out-Null
claude mcp add --scope user pm-guidance -e "PM_GUIDANCE_KEY=$Key" -- python $bridge
Write-Host "bridge          -> registered at user scope ($bridge)"

Write-Host ""
Write-Host "Done. Start a fresh Claude session; the pm-guidance tools will be in it."
