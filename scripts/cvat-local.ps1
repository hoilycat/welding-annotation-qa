[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Action
)

# 예상하지 못한 변수와 명령 오류를 즉시 중단하는 PowerShell 안전 설정
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 실행 위치와 관계없이 저장소 루트와 설정 파일 위치를 계산하는 코드
$script:RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$script:EnvFile = Join-Path $script:RepoRoot ".env.cvat"

# KEY=VALUE 형식의 .env.cvat을 현재 PowerShell process 환경으로 불러오는 함수
function Import-CvatEnvFile {
    if (-not (Test-Path -LiteralPath $script:EnvFile -PathType Leaf)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $script:EnvFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        # 값 내부의 '=' 문자를 보존하기 위해 첫 번째 구분자에서만 나누는 코드
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2 -or $parts[0] -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Invalid environment entry in $($script:EnvFile): $line"
        }

        $name = $parts[0]
        $value = $parts[1]
        # 단순한 따옴표로 감싼 값을 Bash source 결과와 비슷하게 맞추는 처리
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

# 환경변수가 없거나 빈 경우 플랫폼 공통 기본값을 돌려주는 함수
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

# 지원하는 하위 명령과 용도를 출력하는 도움말
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

# PowerShell이 native command 종료 코드를 놓치지 않게 예외로 바꾸는 wrapper
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

# Docker Desktop daemon이 실제로 응답하는지 확인하는 사전 검사
function Assert-DockerRunning {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running. Start Docker Desktop and retry."
    }
}

# 고정한 CVAT tag를 shallow clone하고 기존 checkout의 버전도 확인하는 코드
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

# CVAT checkout에서 host, port, version을 전달해 docker compose를 실행하는 함수
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
    # .env 값, process 환경변수, 기본값 순서로 최종 실행 설정을 만드는 코드
    Import-CvatEnvFile

    $script:CvatVersion = Get-CvatSetting -Name "CVAT_VERSION" -Default "v2.70.0"
    $script:CvatHost = Get-CvatSetting -Name "CVAT_HOST" -Default "localhost"
    $script:CvatPort = Get-CvatSetting -Name "CVAT_PORT" -Default "8080"
    $defaultRuntimeDir = Join-Path $script:RepoRoot ".local\cvat"
    $script:RuntimeDir = [System.IO.Path]::GetFullPath(
        (Get-CvatSetting -Name "CVAT_RUNTIME_DIR" -Default $defaultRuntimeDir)
    )

    # 사용자 명령을 공통 준비 단계와 실제 Docker 작업으로 연결하는 분기
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
    # 내부 stack trace 대신 사용자가 바로 조치할 수 있는 한 줄 오류를 출력하는 처리
    [Console]::Error.WriteLine("error: $($_.Exception.Message)")
    exit 1
}
