<#
.SYNOPSIS
    Turn a table copied out of OOTP into a report file and check it.

.DESCRIPTION
    Copy the ratings table in OOTP (Report -> Write report to disk, then select
    the table including its header row and copy). Run this. It writes the
    clipboard to a .tsv next to the tool and runs `prepare` on it, so the paste
    block is ready for ootpcalculator.com.

.EXAMPLE
    .\capture.ps1
    .\capture.ps1 -Name pitchers
    .\capture.ps1 -Scale "1 to 100"
    .\capture.ps1 -FromFile saved_table.txt
#>
[CmdletBinding()]
param(
    [string]$Name = "pool",
    [string]$Scale = "20 to 80",
    [string]$FromFile
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($FromFile) {
    if (-not (Test-Path $FromFile)) { Write-Error "No such file: $FromFile"; exit 1 }
    $text = Get-Content -Raw -Path $FromFile
    $source = $FromFile
} else {
    $text = Get-Clipboard -Raw
    $source = "the clipboard"
}

if ([string]::IsNullOrWhiteSpace($text)) {
    Write-Error "$source is empty. Copy the ratings table out of OOTP first, including the header row."
    exit 1
}

# OOTP's report table copies as tab-separated text. Anything else means the
# wrong thing was copied - catch it here rather than letting the parser guess.
$lines = $text -split "`r?`n" | Where-Object { $_.Trim() -ne "" }
if ($lines.Count -lt 2) {
    Write-Error "$source holds only $($lines.Count) non-empty line(s). Select the header row and the player rows together."
    exit 1
}
if ($lines[0] -notmatch "`t") {
    Write-Error "The first line of $source has no tabs, so it is not an OOTP report table. Copy the table itself, not a screenshot or a single cell."
    exit 1
}

$destination = Join-Path $root "$Name.tsv"
if (Test-Path $destination) {
    $backup = Join-Path $root "$Name.previous.tsv"
    Move-Item -Path $destination -Destination $backup -Force
    Write-Host "Kept the last $Name.tsv as $Name.previous.tsv" -ForegroundColor DarkGray
}

# UTF8 without BOM, so the loader sees the header cleanly on any machine.
$content = ($lines -join "`n") + "`n"
[System.IO.File]::WriteAllText($destination, $content, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Wrote $($lines.Count - 1) players to $destination" -ForegroundColor Green
Write-Host ""

Push-Location $root
try {
    python -m ootp_scout prepare $destination --scale $Scale
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

# On success, leave the paste block on the clipboard so the next action is a
# plain Ctrl+V on the site - the clipboard held the OOTP table on the way in
# and holds what the calculator wants on the way out.
$pasteBlock = Join-Path $root "$Name.paste.tsv"
if ($code -eq 0 -and (Test-Path $pasteBlock)) {
    [System.IO.File]::ReadAllText($pasteBlock) | Set-Clipboard
    Write-Host ""
    Write-Host "The paste block is on your clipboard - just Ctrl+V into BATCH INPUT." -ForegroundColor Green
}

exit $code
