$Env:HF_HOME = "huggingface"
$Env:MIKAZUKI_TAGGER_MODELS_DIR = "tagger-models"
$Env:PIP_DISABLE_PIP_VERSION_CHECK = 1
$Env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"

. "$PSScriptRoot\install_preflight.ps1"

function InstallFail {
    Write-Output "安装失败。"
    Read-Host | Out-Null
    Exit 1
}

function Check {
    param (
        $ErrorInfo
    )
    if (!($?)) {
        Write-Output $ErrorInfo
        InstallFail
    }
}

$PytorchSources = @(
    @{
        Name = "阿里云 PyTorch Wheels"
        Mode = "find-links"
        Url = "https://mirrors.aliyun.com/pytorch-wheels/cu128/"
    },
    @{
        Name = "SJTUG PyTorch Wheels"
        Mode = "index-url"
        Url = "https://mirror.sjtu.edu.cn/pytorch-wheels/cu128"
    },
    @{
        Name = "PyTorch Official"
        Mode = "index-url"
        Url = "https://download.pytorch.org/whl/cu128"
    }
)

$TorchInstallRetriesPerSource = 5
$PackageInstallRetriesPerSource = 2

function Test-PytorchSource {
    param ($Source)

    $start = Get-Date
    try {
        Invoke-WebRequest -Uri $Source.Url -UseBasicParsing -TimeoutSec 8 | Out-Null
        $elapsed = ((Get-Date) - $start).TotalSeconds
        [PSCustomObject]@{
            Name = $Source.Name
            Mode = $Source.Mode
            Url = $Source.Url
            Elapsed = $elapsed
            Ok = $true
        }
    }
    catch {
        [PSCustomObject]@{
            Name = $Source.Name
            Mode = $Source.Mode
            Url = $Source.Url
            Elapsed = [double]::PositiveInfinity
            Ok = $false
            Error = $_.Exception.Message
        }
    }
}

function Select-PytorchSources {
    Write-Host "正在测速 PyTorch 下载源..."
    $jobs = foreach ($source in $PytorchSources) {
        Start-Job -ScriptBlock ${function:Test-PytorchSource} -ArgumentList $source
    }

    $results = @()
    while ($jobs.Count -gt 0) {
        $completed = Wait-Job -Job $jobs -Any
        $result = Receive-Job -Job $completed
        Remove-Job -Job $completed
        $jobs = @($jobs | Where-Object { $_.Id -ne $completed.Id })
        $results += $result

        if ($result.Ok) {
            Write-Host ("  OK   {0} ({1:N2}s)" -f $result.Name, $result.Elapsed)
        }
        else {
            Write-Host ("  FAIL {0} ({1})" -f $result.Name, $result.Error)
        }
    }

    $available = @($results | Where-Object { $_.Ok } | Sort-Object Elapsed)
    if ($available.Count -eq 0) {
        Write-Host "所有 PyTorch 下载源均无法连接，请检查网络或代理设置后重试。"
        InstallFail
    }

    Write-Host ("已选择最快源: {0}" -f $available[0].Name)
    return $available
}

function Get-PipSourceArgs {
    param ($Source)

    if ($Source.Mode -eq "find-links") {
        return @("-f", $Source.Url)
    }
    return @("--index-url", $Source.Url)
}

function Invoke-PipInstallWithRetries {
    param (
        [string]$Label,
        [string[]]$PackageArgs,
        $Source,
        [int]$RetriesPerSource
    )

    $sourceArgs = Get-PipSourceArgs $Source
    for ($attempt = 1; $attempt -le $RetriesPerSource; $attempt++) {
        if ($attempt -gt 1) {
            Write-Output ("{0} 网络波动，继续使用当前源重试 ({1}/{2}): {3}" -f $Label, $attempt, $RetriesPerSource, $Source.Name)
        }

        python -m pip install --retries 5 --timeout 60 --resume-retries 5 @PackageArgs @sourceArgs
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    }

    return $false
}

function Test-PythonModuleAvailable {
    param (
        [string]$ModuleName
    )

    python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-InstallScriptFreshness)) { InstallFail }

if (Test-Path -Path "python\python.exe") {
    Write-Output "使用 python 文件夹中的 python..."
    $py_path = (Get-Item "python").FullName
    $env:PATH = "$py_path;$env:PATH"
    if (-not (Test-InstallPython)) { InstallFail }
}
else {
    if (-not (Test-InstallPython)) { InstallFail }

    # Sync vendor/sd-scripts submodule (Anima training engine)
    if ((Test-Path -Path ".git") -or (Test-Path -Path ".git" -PathType Leaf)) {
        Write-Output "同步 git 子模块 (vendor/sd-scripts)..."
        git submodule update --init --recursive
        if ($LASTEXITCODE -ne 0) {
            Write-Output "警告: 子模块初始化失败，Anima 训练可能无法启动。请手动运行: git submodule update --init --recursive"
        }
    }

    if (!(Test-Path -Path "venv")) {
        Write-Output "正在创建虚拟环境..."
        python -m venv venv
        Check "创建虚拟环境失败，请检查 python 是否安装正确以及 python 版本是否为 64 位版本 (python 3.10)，python 的目录是否在环境变量 PATH 中。"
    }

    Write-Output "检测到虚拟环境，正在激活..."
    .\venv\Scripts\activate
    Check "激活虚拟环境失败。"
}

Write-Output "安装训练依赖 (已进行国内加速，如在国外无法使用加速源请换用 install.ps1 脚本)"
Write-Output "Torch 将自动测速多个下载源并选择最快可用源。"
$needTorch = -not (Test-PythonModuleAvailable "torch")
$needXformers = -not (Test-PythonModuleAvailable "xformers")
if ($needTorch -or $needXformers) {
    $pytorchSources = @(Select-PytorchSources)
    $pytorchSource = $null
    if ($needTorch) {
        $torchInstalled = $false

        foreach ($source in $pytorchSources) {
            if ($null -ne $pytorchSource) {
                Write-Output ("Torch 当前源连续失败，正在尝试备用源: {0}" -f $source.Name)
            }
            $pytorchSource = $source
            Write-Output ("未检测到 Torch，正在安装 Torch，当前源: {0}" -f $pytorchSource.Name)
            if (Invoke-PipInstallWithRetries -Label "Torch" -PackageArgs @("torch==2.7.0+cu128", "torchvision==0.22.0+cu128") -Source $pytorchSource -RetriesPerSource $TorchInstallRetriesPerSource) {
                $torchInstalled = $true
                break
            }
        }

        if (-not $torchInstalled) {
            Write-Output "所有可连接的 PyTorch 下载源均安装失败，请删除 venv 文件夹后重新运行。"
            InstallFail
        }
    }
    else {
        Write-Output "检测到已安装 Torch，跳过 Torch 安装。"
        $pytorchSource = $pytorchSources[0]
    }

    if ($needXformers) {
        Write-Output "未检测到 xformers，正在安装 xformers..."
        if (-not (Invoke-PipInstallWithRetries -Label "xformers" -PackageArgs @("-U", "-I", "--no-deps", "xformers==0.0.30") -Source $pytorchSource -RetriesPerSource $PackageInstallRetriesPerSource)) {
            Write-Output "xformers 使用当前源安装失败，正在回退到 PyTorch 官方源..."
            $officialSource = @{
                Name = "PyTorch Official"
                Mode = "index-url"
                Url = "https://download.pytorch.org/whl/cu128"
            }
            if (-not (Invoke-PipInstallWithRetries -Label "xformers" -PackageArgs @("-U", "-I", "--no-deps", "xformers==0.0.30") -Source $officialSource -RetriesPerSource $PackageInstallRetriesPerSource)) {
                Write-Output "xformers 安装失败。"
                InstallFail
            }
        }
    }
    else {
        Write-Output "检测到已安装 xformers，跳过 xformers 安装。"
    }
}
else {
    Write-Output "检测到已安装 Torch 和 xformers，跳过 Torch/xformers 安装。"
}

$requirementsSource = @{
    Name = "Python 镜像源"
    Mode = "index-url"
    Url = $Env:PIP_INDEX_URL
}
if (-not (Invoke-PipInstallWithRetries -Label "训练依赖" -PackageArgs @("--upgrade", "-r", "requirements.txt") -Source $requirementsSource -RetriesPerSource $PackageInstallRetriesPerSource)) {
    Write-Output "训练依赖库安装失败。"
    InstallFail
}

Write-Output "预下载默认 WD 打标模型 wd14-convnextv2-v2（约 388MB，首次较慢）..."
python scripts/prefetch_default_tagger.py --if-missing --tagger-models-dir "$Env:MIKAZUKI_TAGGER_MODELS_DIR"
if ($LASTEXITCODE -ne 0) {
    Write-Output "警告: 默认打标模型预下载失败，可在启动后于「打标」页首次使用时自动下载。"
}

Write-Output "安装完成"
Write-Output ""
Write-Output "可选：运行 install_flash_attn.bat 启用 Flash Attention 2 加速。"
Read-Host | Out-Null
