# Windows PowerShell 5.1. Keep this file beside STOP_BUNKER.bat.
[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$gameFolder = [IO.Path]::GetFullPath($PSScriptRoot)
$script:changed = 0
$script:problems = 0
$dataRoots = @()
if ($env:LOCALAPPDATA) {
    $installed = Join-Path $env:LOCALAPPDATA 'Bunker'
    if (Test-Path -LiteralPath $installed -PathType Container) {
        $dataRoots += @(Get-ChildItem -LiteralPath $installed -Directory | Select-Object -ExpandProperty FullName)
    }
}
$dataRoots += Join-Path $gameFolder 'BunkerData'
$dataRoots = @($dataRoots | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Sort-Object -Unique)

function Same-Path([string]$Left, [string]$Right) {
    if (-not $Left -or -not $Right) { return $false }
    try {
        return [IO.Path]::GetFullPath($Left).TrimEnd('\').Equals(
            [IO.Path]::GetFullPath($Right).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Read-Launcher($Record) {
    # Do not send the local token to arbitrary hosts or follow redirects.
    Invoke-RestMethod -Uri ($Record.origin + '/api/status') -Method Get `
        -Headers @{'X-Bunker-Token' = $Record.token} -TimeoutSec 2 -MaximumRedirection 0
}

function Get-LocalLaunchers {
    @(Get-Process -Name Bunker,Bunker_Random,Bunker_Portable -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and (Same-Path ([IO.Path]::GetDirectoryName($_.Path)) $gameFolder)
    })
}

function Stop-CheckedProcess($Process, [string]$Label) {
    if ($CheckOnly) {
        Write-Host ('Найден {0}: PID {1}, {2}' -f $Label, $Process.Id, $Process.Path)
        return
    }
    try {
        # Acquire a handle before stopping; do not act on a stale PID alone.
        $null = $Process.Handle
        if ($Process.HasExited) { return }
        Stop-Process -InputObject $Process -Force -ErrorAction Stop
        if (-not $Process.WaitForExit(5000)) { throw 'Process did not exit' }
        $script:changed++
        Write-Host ('Закрыт {0} (PID {1}).' -f $Label, $Process.Id)
    } catch {
        if (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue) {
            $script:problems++
            Write-Host ('Не удалось закрыть {0} (PID {1}). Если игра запущена от администратора, запустите батник так же.' -f $Label, $Process.Id) -ForegroundColor Yellow
        }
    }
}

# Ask every installed/portable launcher to shut down its own server first.
# Its exit handler also closes the tray icon, sockets and instance files.
foreach ($dataRoot in $dataRoots) {
    $instanceFile = Join-Path $dataRoot 'instance.json'
    if (-not (Test-Path -LiteralPath $instanceFile -PathType Leaf)) { continue }
    try {
        $record = Get-Content -LiteralPath $instanceFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $address = [uri]$record.origin
        if ($address.Scheme -ne 'http' -or $address.Host -ne '127.0.0.1' -or
            $address.Port -lt 1 -or $address.UserInfo -or $address.Query -or
            $address.Fragment -or $address.AbsolutePath -ne '/' -or
            $record.token -notmatch '^[0-9a-fA-F]{64}$') { continue }
        $status = Read-Launcher $record
        if (-not (Same-Path $status.data_dir $dataRoot) -or $status.version -notmatch '^4\.\d+\.\d+$') { continue }
    } catch {
        # An old instance.json is not proof of a running process.
        continue
    }
    Write-Host ('Найден помощник Бункера {0}, состояние: {1}.' -f $status.version, $status.phase)
    if ($CheckOnly) { continue }
    try {
        $answer = Invoke-RestMethod -Uri ($record.origin + '/api/exit') -Method Post `
            -Headers @{'X-Bunker-Token' = $record.token} -TimeoutSec 7 -MaximumRedirection 0
        if (-not $answer.ok) { throw 'Shutdown rejected' }
        $closed = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Milliseconds 200
            if (-not (Test-Path -LiteralPath $instanceFile)) { $closed = $true; break }
        }
        if ($closed) {
            $script:changed++
            Write-Host 'Помощник завершён вместе с его сервером.'
        } else {
            Write-Host 'Помощник не завершился вовремя. Проверяю процессы игры.' -ForegroundColor Yellow
        }
    } catch {
        Write-Host 'Команда завершения не выполнена. Проверяю процессы игры.' -ForegroundColor Yellow
    }
}

# A frozen launcher may no longer answer HTTP. Only stop known executables
# beside this script, never all processes sharing the same name.
foreach ($process in (Get-LocalLaunchers)) {
    Stop-CheckedProcess $process 'помощник Бункера'
}

# Recover a server left without its launcher. Require BOTH the Python executable
# and the complete server script argument to belong to a known game directory.
$serverTargets = @()
foreach ($dataRoot in $dataRoots) {
    foreach ($pythonName in @('python.exe', 'pythonw.exe')) {
        $serverTargets += [pscustomobject]@{
            Exe = Join-Path $dataRoot ('runtime\' + $pythonName)
            Script = Join-Path $dataRoot 'app\desktop_server.py'
        }
    }
}
$pythonProcesses = @(Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object {
    $candidate = $_
    @($serverTargets | Where-Object { Same-Path $candidate.Path $_.Exe }).Count -gt 0
})
foreach ($process in $pythonProcesses) {
    try {
        $info = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $process.Id) -ErrorAction Stop
        $owned = @($serverTargets | Where-Object {
            (Same-Path $info.ExecutablePath $_.Exe) -and
            $info.CommandLine -match ('(?:^|[\s"])' + [regex]::Escape($_.Script) + '(?=[\s"]|$)')
        }).Count -gt 0
        if ($owned) {
            Stop-CheckedProcess $process 'сервер Бункера'
        } else {
            $script:problems++
            Write-Host ('Python из папки игры (PID {0}) не опознан как сервер и оставлен работающим.' -f $process.Id) -ForegroundColor Yellow
        }
    } catch {
        if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) { continue }
        $script:problems++
        Write-Host ('Не удалось проверить процесс игры PID {0}. Попробуйте запуск батника от администратора.' -f $process.Id) -ForegroundColor Yellow
    }
}

if ($CheckOnly) {
    Write-Host 'Проверка закончена. Процессы не остановлены.'
    exit 0
}

# Verify shutdown instead of claiming success solely from an accepted POST.
$stillRunning = @(Get-LocalLaunchers)
foreach ($dataRoot in $dataRoots) {
    $instanceFile = Join-Path $dataRoot 'instance.json'
    if (-not (Test-Path -LiteralPath $instanceFile -PathType Leaf)) { continue }
    try {
        $record = Get-Content -LiteralPath $instanceFile -Raw -Encoding UTF8 | ConvertFrom-Json
        # Reuse the same strict address validation for this fresh read.
        $address = [uri]$record.origin
        if ($address.Scheme -ne 'http' -or $address.Host -ne '127.0.0.1' -or
            $address.UserInfo -or $address.Query -or $address.Fragment -or
            $address.AbsolutePath -ne '/' -or $record.token -notmatch '^[0-9a-fA-F]{64}$') { continue }
        $status = Read-Launcher $record
        if ((Same-Path $status.data_dir $dataRoot) -and $status.version -match '^4\.\d+\.\d+$') {
            $stillRunning += $status
        }
    } catch { }
}
if ($stillRunning.Count -or $script:problems) {
    Write-Host 'Не все процессы удалось закрыть или проверить. Смотрите сообщения выше.' -ForegroundColor Yellow
    exit 1
}
if ($script:changed) {
    Write-Host 'Готово. Бункер закрыт. Теперь можно запускать нужную сборку.' -ForegroundColor Green
} else {
    Write-Host 'Запущенный Бункер не найден. Уже всё закрыто.' -ForegroundColor Green
}
exit 0
