import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

AUTODL_HOST = "https://www.autodl.art"

TOKEN = os.environ.get("AUTODL_TOKEN", "").strip()
INSTANCE_UUID = os.environ.get("AUTODL_INSTANCE_UUID", "").strip()
START_COMMAND = os.environ.get("AUTODL_START_COMMAND", "").strip()

LEASE_HEALTH_URL = os.environ.get("LEASE_HEALTH_URL", "").strip()

SSH_HOST = os.environ.get("AUTODL_SSH_HOST", "").strip()
SSH_PORT = os.environ.get("AUTODL_SSH_PORT", "").strip()
SSH_USER = os.environ.get("AUTODL_SSH_USER", "root").strip()
SSH_KEY = os.environ.get("AUTODL_SSH_KEY", "").strip()
SSH_START_COMMAND = os.environ.get(
    "AUTODL_SSH_START_COMMAND",
    "screen -wipe; cd /root/autodl-tmp/llm_api; bash start_all.sh",
).strip()

MAX_WAIT_SECONDS = int(os.environ.get("AUTODL_MAX_WAIT_SECONDS", "900"))
RETRY_SECONDS = int(os.environ.get("AUTODL_RETRY_SECONDS", "15"))
SSH_FALLBACK_AFTER_ATTEMPTS = int(os.environ.get("AUTODL_SSH_FALLBACK_AFTER_ATTEMPTS", "2"))


def log(msg):
    print("[AutoDL] " + str(msg), flush=True)


def api_request(method, path, payload=None, timeout=30):
    if not TOKEN:
        raise RuntimeError("AUTODL_TOKEN is empty")
    if not INSTANCE_UUID:
        raise RuntimeError("AUTODL_INSTANCE_UUID is empty")

    data = None

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url=AUTODL_HOST + path,
        data=data,
        method=method,
        headers={
            "Authorization": TOKEN,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return json.loads(text)

    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except Exception:
            raise RuntimeError("HTTP {}: {}".format(e.code, text)) from e

    except urllib.error.URLError as e:
        raise RuntimeError("Network error: {}".format(e)) from e


def check_url(url, timeout=5):
    if not url:
        return False

    try:
        req = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                "User-Agent": "ComfyUI-AutoDL-PowerOn",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500

    except Exception:
        return False


def power_on_once():
    payload = {
        "instance_uuid": INSTANCE_UUID,
        "payload": "gpu",
    }

    if START_COMMAND:
        payload["start_command"] = START_COMMAND

    return api_request(
        "POST",
        "/api/v1/adl_dev/dev/instance/pro/power_on",
        payload,
    )


def classify_power_on_response(res):
    code = str(res.get("code", ""))
    msg = str(res.get("msg", ""))

    if code == "Success":
        return "success"

    hard_errors = [
        "暂无库存",
        "库存不足",
        "算力规格暂无库存",
        "请修改配置",
    ]

    if any(x in msg for x in hard_errors):
        return "no_stock"

    retryable_errors = [
        "当前实例状态无法进行开机操作",
        "请稍后再试",
        "稍后再试",
        "状态",
    ]

    if any(x in msg for x in retryable_errors):
        return "retry"

    if code in ["BadRequest", "RequestParameterIsWrong"]:
        return "retry"

    return "fatal"


def run_ssh_start_all():
    if not SSH_HOST or not SSH_PORT:
        log("SSH fallback skipped: AUTODL_SSH_HOST or AUTODL_SSH_PORT is empty")
        return False

    target = f"{SSH_USER}@{SSH_HOST}"

    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=10",
        "-p", SSH_PORT,
    ]

    if SSH_KEY:
        cmd.extend(["-i", SSH_KEY])

    cmd.extend([target, SSH_START_COMMAND])

    log("SSH fallback: trying to run remote start_all.sh")
    log("SSH target: {}:{}".format(SSH_HOST, SSH_PORT))
    log("Remote command: {}".format(SSH_START_COMMAND))

    try:
        # 不 capture_output，方便没有 SSH key 时直接在窗口输入 root 密码。
        result = subprocess.run(
            cmd,
            timeout=180,
        )

        if result.returncode == 0:
            log("SSH fallback finished")
            return True

        log("SSH fallback failed, returncode={}".format(result.returncode))
        return False

    except FileNotFoundError:
        log("SSH fallback failed: Windows ssh command not found")
        return False

    except subprocess.TimeoutExpired:
        log("SSH fallback failed: timeout")
        return False

    except Exception as e:
        log("SSH fallback failed: {}".format(e))
        return False


def main():
    if not LEASE_HEALTH_URL:
        raise RuntimeError("LEASE_HEALTH_URL is empty")

    deadline = time.time() + MAX_WAIT_SECONDS
    attempt = 0
    last_response = None
    ssh_used = False

    log("target lease health: {}".format(LEASE_HEALTH_URL))
    log("max wait seconds: {}".format(MAX_WAIT_SECONDS))

    while time.time() < deadline:
        attempt += 1

        # 1. 只要 /health 通，就认为远端守护已经可用。
        if check_url(LEASE_HEALTH_URL):
            log("lease_guard is reachable")
            log("remote LLM lease_guard is ready")
            return

        # 2. /health 不通，尝试 API power_on。
        log("lease_guard not reachable. requesting power_on, attempt={}".format(attempt))

        try:
            res = power_on_once()
            last_response = res
            log("power_on response: {}".format(res))

        except Exception as e:
            log("power_on request failed: {}".format(e))
            time.sleep(RETRY_SECONDS)
            continue

        kind = classify_power_on_response(res)

        if kind == "success":
            log("power_on accepted. waiting for remote start_command/start_all.sh...")
            time.sleep(RETRY_SECONDS)
            continue

        if kind == "retry":
            log("power_on not accepted yet, but retryable.")

            # 关键补救：
            # 实例可能已经手动开机，但远端 start_all.sh 没有执行。
            # 这种情况下通过 SSH 自动补跑 start_all.sh。
            if attempt >= SSH_FALLBACK_AFTER_ATTEMPTS and not ssh_used:
                ssh_used = True

                log("health still unavailable. running SSH fallback once.")
                run_ssh_start_all()

                time.sleep(RETRY_SECONDS)

                if check_url(LEASE_HEALTH_URL):
                    log("lease_guard is reachable after SSH fallback")
                    log("remote LLM lease_guard is ready")
                    return

            log("wait and retry.")
            time.sleep(RETRY_SECONDS)
            continue

        if kind == "no_stock":
            raise RuntimeError(
                "AutoDL reports no stock or configuration unavailable. "
                "Raw response: {}".format(res)
            )

        raise RuntimeError("power_on fatal response: {}".format(res))

    raise RuntimeError(
        "timeout waiting for remote lease_guard. "
        "last power_on response: {}".format(last_response)
    )


if __name__ == "__main__":
    try:
        main()

    except Exception as e:
        log("ERROR: {}".format(e))
        sys.exit(1)
