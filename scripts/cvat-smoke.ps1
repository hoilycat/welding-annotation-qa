[CmdletBinding()]
param(
    [string]$Images,
    [string]$Annotations,
    [string]$ExportDir,
    [string]$Modality = "RT",
    [string]$ProjectName,
    [string]$TaskName,
    [switch]$Replace,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$envFile = Join-Path $repoRoot ".env.cvat"

function Show-Usage {
    @"
Usage: powershell -ExecutionPolicy Bypass -File scripts/cvat-smoke.ps1 -Images DIR -ExportDir DIR [options]

Options:
  -Images DIR          Image directory to upload (required)
  -Annotations DIR     RIAWELC JSON directory to synchronize
  -ExportDir DIR       Directory for canonical JSON export (required)
  -Modality MODALITY   RT or VT (default: RT)
  -ProjectName NAME    Existing/new CVAT Project name
  -TaskName NAME       Existing/new CVAT Task name
  -Replace             Explicitly replace existing Task annotations
  -Help                Show this help

Set the PYTHON environment variable to select the Python executable.
"@
}

function Import-CvatEnvFile {
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2 -or $parts[0] -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Invalid environment entry in $($envFile): $line"
        }
        $value = $parts[1]
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        Set-Item -LiteralPath "Env:$($parts[0])" -Value $value
    }
}

function Invoke-QaModule {
    param([string[]]$Arguments)

    & $python -m welding_qa.cvat_task @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "welding_qa.cvat_task exited with code $LASTEXITCODE."
    }
}

if ($Help) {
    Show-Usage
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Images) -or [string]::IsNullOrWhiteSpace($ExportDir)) {
    Show-Usage
    throw "-Images and -ExportDir are required."
}

Import-CvatEnvFile
$python = if ([string]::IsNullOrWhiteSpace($env:PYTHON)) { "python" } else { $env:PYTHON }
$imagesPath = [System.IO.Path]::GetFullPath($Images)
$exportPath = [System.IO.Path]::GetFullPath($ExportDir)
if (-not (Test-Path -LiteralPath $imagesPath -PathType Container)) {
    throw "Image directory does not exist: $imagesPath"
}
$annotationsPath = $null
if ($Annotations) {
    $annotationsPath = [System.IO.Path]::GetFullPath($Annotations)
    if (-not (Test-Path -LiteralPath $annotationsPath -PathType Container)) {
        throw "Annotation directory does not exist: $annotationsPath"
    }
}

$commonArgs = [System.Collections.Generic.List[string]]::new()
$commonArgs.Add("--modality"); $commonArgs.Add($Modality)
$commonArgs.Add("--images"); $commonArgs.Add($imagesPath)
if ($ProjectName) { $commonArgs.Add("--project-name"); $commonArgs.Add($ProjectName) }
if ($TaskName) { $commonArgs.Add("--task-name"); $commonArgs.Add($TaskName) }

Push-Location -LiteralPath $repoRoot
try {
    if ($annotationsPath) {
        Write-Output "[1/2] Validate input, upload images, and synchronize annotations"
        $syncArgs = [System.Collections.Generic.List[string]]::new()
        $syncArgs.AddRange($commonArgs)
        $syncArgs.Add("--annotations"); $syncArgs.Add($annotationsPath)
        if ($Replace) { $syncArgs.Add("--replace-annotations") }
        Invoke-QaModule -Arguments $syncArgs.ToArray()
    }
    else {
        Write-Output "[1/2] Ensure CVAT Task and upload images"
        Invoke-QaModule -Arguments $commonArgs.ToArray()
    }

    Write-Output "[2/2] Export and validate canonical JSON"
    $exportArgs = [System.Collections.Generic.List[string]]::new()
    $exportArgs.AddRange($commonArgs)
    $exportArgs.Add("--export-annotations"); $exportArgs.Add($exportPath)
    Invoke-QaModule -Arguments $exportArgs.ToArray()

    $validationArgs = [System.Collections.Generic.List[string]]::new()
    $validationArgs.Add("--images"); $validationArgs.Add($imagesPath)
    $validationArgs.Add("--export-dir"); $validationArgs.Add($exportPath)
    $validationArgs.Add("--modality"); $validationArgs.Add($Modality)
    if ($annotationsPath) {
        $validationArgs.Add("--annotations"); $validationArgs.Add($annotationsPath)
    }
    $validationArgumentArray = $validationArgs.ToArray()
    & $python -m welding_qa.smoke_validation @validationArgumentArray
    if ($LASTEXITCODE -ne 0) {
        throw "Export validation failed with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
