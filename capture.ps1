<#
.SYNOPSIS
    Get an OOTP ratings export ready for ootpcalculator.com.

.DESCRIPTION
    Two ways in, both ending with the paste block on your clipboard:

    -Report <file>  the HTML file OOTP writes for "Report -> Write report to
                    disk". Nothing to copy by hand - this is the easy one.

    (no argument)   reads the clipboard, for when you have selected the table
                    in the browser and copied it yourself.

.EXAMPLE
    .\capture.ps1 -Report "$env:USERPROFILE\Documents\OOTP\reports\players.html"
    .\capture.ps1 -Report players.html -Name pitchers
    .\capture.ps1
    .\capture.ps1 -Scale "1 to 100"
#>
[CmdletBinding()]
param(
    [Alias("FromFile")]
    [string]$Report,
    [string]$Name = "pool",
    [string]$Scale = "20 to 80"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Report) {
    if (-not (Test-Path $Report)) {
        Write-Error "No such file: $Report"
        exit 1
    }
    # The loader reads OOTP's HTML directly, so the export is used as-is.
    $target = (Resolve-Path $Report).Path
    Write-Host "Reading $target" -ForegroundColor Green
} else {
    $text = Get-Clipboard -Raw
    if ([string]::IsNullOrWhiteSpace($text)) {
        Write-Error "The clipboard is empty. Either copy the ratings table out of OOTP, or pass -Report with the HTML file OOTP wrote."
        exit 1
    }

    # OOTP's report table copies as tab-separated text. Anything else means the
    # wrong thing was copied - catch it here rather than letting it fail later.
    $lines = $text -split "`r?`n" | Where-Object { $_.Trim() -ne "" }
    if ($lines.Count -lt 2) {
        Write-Error "The clipboard holds only $($lines.Count) non-empty line(s). Select the header row and the player rows together."
        exit 1
    }
    if ($lines[0] -notmatch "`t") {
        Write-Error "The first clipboard line has no tabs, so it is not an OOTP report table. Copy the table itself, or pass -Report with the HTML file instead."
        exit 1
    }

    $target = Join-Path $root "$Name.tsv"
    if (Test-Path $target) {
        Move-Item -Path $target -Destination (Join-Path $root "$Name.previous.tsv") -Force
        Write-Host "Kept the last $Name.tsv as $Name.previous.tsv" -ForegroundColor DarkGray
    }

    # UTF8 without BOM, so the loader sees the header cleanly on any machine.
    $content = ($lines -join "`n") + "`n"
    [System.IO.File]::WriteAllText($target, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Wrote $($lines.Count - 1) players to $target" -ForegroundColor Green
}

Write-Host ""

Push-Location $root
try {
    python -m ootp_scout prepare $target --scale $Scale --out (Join-Path $root "$Name.paste.tsv")
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

# On success, leave the paste block on the clipboard so the next action is a
# plain Ctrl+V on the site.
$pasteBlock = Join-Path $root "$Name.paste.tsv"
if ($code -eq 0 -and (Test-Path $pasteBlock)) {
    [System.IO.File]::ReadAllText($pasteBlock) | Set-Clipboard
    Write-Host ""
    Write-Host "The paste block is on your clipboard - just Ctrl+V into BATCH INPUT." -ForegroundColor Green
    Write-Host "Afterwards, download the CSV and run:" -ForegroundColor DarkGray
    Write-Host "  python -m ootp_scout flag `"$target`" `"$env:USERPROFILE\Downloads\batter-projections.csv`" --out targets.csv" -ForegroundColor DarkGray
}

exit $code
