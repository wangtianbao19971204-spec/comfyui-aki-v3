from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_install_cn_keeps_pip_cache_enabled_for_large_downloads():
    script = (ROOT / "install-cn.ps1").read_text(encoding="utf-8")

    assert "$Env:PIP_NO_CACHE_DIR = 1" not in script


def test_install_cn_uses_retry_helper_for_torch_and_xformers():
    script = (ROOT / "install-cn.ps1").read_text(encoding="utf-8")

    assert "Invoke-PipInstallWithRetries" in script
    assert "Test-PythonModuleAvailable" in script
    assert "$TorchInstallRetriesPerSource = 5" in script
    assert "$PackageInstallRetriesPerSource = 2" in script
    assert "torch==2.7.0+cu128" in script
    assert "torchvision==0.22.0+cu128" in script
    assert "xformers==0.0.30" in script
    assert 'Read-Host "是否需要安装 Torch+xformers?' not in script
    assert '检测到已安装 Torch 和 xformers，跳过 Torch/xformers 安装。' in script
    assert 'PackageArgs @("--upgrade", "-r", "requirements.txt")' in script
