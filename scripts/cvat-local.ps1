[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Action
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$script:EnvFile = Join-Path $script:RepoRoot ".env.cvat"

function Import-CvatEnvFile {
    if (-not (Test-Path -LiteralPath $script:EnvFile -PathType Leaf)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $script:EnvFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2 -or $parts[0] -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Invalid environment entry in $($script:EnvFile): $line"
        }

        $name = $parts[0]
        $value = $parts[1]
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        Set-Item -LiteralPath "Env:$name" -Value $value
    }
}

function Get-CvatSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Default
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrEmpty($value)) {
        return $Default
    }
    return $value
}

function Show-Usage {
    @"
Usage: powershell -ExecutionPolicy Bypass -File scripts/cvat-local.ps1 <command>

Commands:
  bootstrap   Clone the pinned CVAT release into .local/cvat
  pull        Pull the pinned CVAT container images
  up          Start the local CVAT stack
  down        Stop the stack without deleting its data volumes
  status      Show container status
  health      Run CVAT's server health check
  logs        Follow CVAT server logs
  superuser   Create a CVAT administrator interactively
  url         Print the local CVAT URL
"@
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE."
    }
}

function Assert-DockerRunning {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running. Start Docker Desktop and retry."
    }
}

function Initialize-CvatSource {
    $gitDirectory = Join-Path $script:RuntimeDir ".git"
    if (-not (Test-Path -LiteralPath $gitDirectory -PathType Container)) {
        $parentDirectory = Split-Path -Parent $script:RuntimeDir
        New-Item -ItemType Directory -Force -Path $parentDirectory | Out-Null
        Invoke-NativeCommand -FilePath "git" -ArgumentList @(
            "clone", "--depth", "1", "--branch", $script:CvatVersion,
            "https://github.com/cvat-ai/cvat.git", $script:RuntimeDir
        )
    }

    $installedVersion = (& git -C $script:RuntimeDir describe --tags --exact-match 2>$null)
    if ($LASTEXITCODE -ne 0) {
        $installedVersion = $null
    }
    if ($installedVersion -ne $script:CvatVersion) {
        $foundVersion = if ($installedVersion) { $installedVersion } else { "an untagged checkout" }
        throw "Expected CVAT $($script:CvatVersion), found $foundVersion. Set CVAT_RUNTIME_DIR to another directory or update the existing checkout."
    }
}

function Invoke-CvatCompose {
    param([string[]]$ArgumentList)

    $env:CVAT_VERSION = $script:CvatVersion
    $env:CVAT_HOST = $script:CvatHost
    $env:CVAT_PORT = $script:CvatPort

    Push-Location -LiteralPath $script:RuntimeDir
    try {
        Invoke-NativeCommand -FilePath "docker" -ArgumentList (@("compose") + $ArgumentList)
    }
    finally {
        Pop-Location
    }
}

try {
    Import-CvatEnvFile

    $script:CvatVersion = Get-CvatSetting -Name "CVAT_VERSION" -Default "v2.70.0"
    $script:CvatHost = Get-CvatSetting -Name "CVAT_HOST" -Default "localhost"
    $script:CvatPort = Get-CvatSetting -Name "CVAT_PORT" -Default "8080"
    $defaultRuntimeDir = Join-Path $script:RepoRoot ".local\cvat"
    $script:RuntimeDir = [System.IO.Path]::GetFullPath(
        (Get-CvatSetting -Name "CVAT_RUNTIME_DIR" -Default $defaultRuntimeDir)
    )

    switch ($Action) {
        "bootstrap" {
            Initialize-CvatSource
            Write-Output "CVAT $($script:CvatVersion) is ready in $($script:RuntimeDir)"
        }
        "pull" {
            Assert-DockerRunning
            Initialize-CvatSource
            Invoke-CvatCompose -ArgumentList @("pull")
        }
        "up" {
            Assert-DockerRunning
            Initialize-CvatSource
            Invoke-CvatCompose -ArgumentList @("up", "-d")
            Write-Output "CVAT is starting at http://$($script:CvatHost):$($script:CvatPort)"
        }
        "down" {
            Assert-DockerRunning
            Initialize-CvatSource
            Invoke-CvatCompose -ArgumentList @("down")
        }
        "status" {
            Assert-DockerRunning
            Initialize-CvatSource
            Invoke-CvatCompose -ArgumentList @("ps")
        }
        "health" {
            Assert-DockerRunning
            Invoke-NativeCommand -FilePath "docker" -ArgumentList @(
                "exec", "-t", "cvat_server", "python", "manage.py", "health_check"
            )
        }
        "logs" {
            Assert-DockerRunning
            Initialize-CvatSource
            Invoke-CvatCompose -ArgumentList @("logs", "--follow", "cvat_server")
        }
        "superuser" {
            Assert-DockerRunning
            Invoke-NativeCommand -FilePath "docker" -ArgumentList @(
                "exec", "-it", "cvat_server", "bash", "-ic", "python3 ~/manage.py createsuperuser"
            )
        }
        "url" {
            Write-Output "http://$($script:CvatHost):$($script:CvatPort)"
        }
        default {
            Show-Usage
            exit 1
        }
    }
}
catch {
    [Console]::Error.WriteLine("error: $($_.Exception.Message)")
    exit 1
}
