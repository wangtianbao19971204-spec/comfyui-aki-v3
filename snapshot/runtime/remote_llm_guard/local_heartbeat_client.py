import json
import os
import time
import urllib.request
import urllib.error

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
LEASE_HEARTBEAT_URL = os.environ.get("LEASE_HEARTBEAT_URL", "").strip()
LEASE_SECRET = os.environ.get("LEASE_SECRET", "").strip()

CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "30"))

LOG_PATH = os.environ.get(
    "LOCAL_HEARTBEAT_LOG_PATH",
    r"G:\ComfyUI-aki-v3\remote_llm_guard\local_heartbeat_client.log"
)


def log(msg):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg)
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http_get_ok(url, timeout=3):
    try:
        req = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                "User-Agent": "ComfyUI-Local-Heartbeat-Client",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def comfy_is_alive():
    urls = [
        COMFY_URL + "/system_stats",
        COMFY_URL + "/",
    ]

    for url in urls:
        if http_get_ok(url):
            return True

    return False


def send_heartbeat():
    if not LEASE_HEARTBEAT_URL:
        raise RuntimeError("LEASE_HEARTBEAT_URL is empty")
    if not LEASE_SECRET:
        raise RuntimeError("LEASE_SECRET is empty")

    data = b"{}"

    req = urllib.request.Request(
        url=LEASE_HEARTBEAT_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Lease-Secret": LEASE_SECRET,
            "User-Agent": "ComfyUI-Local-Heartbeat-Client",
        },
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    try:
        payload = json.loads(text)
    except Exception:
        raise RuntimeError("heartbeat response is not json: " + text)

    if not payload.get("ok"):
        raise RuntimeError("heartbeat rejected: " + text)

    return payload


def main():
    log("local heartbeat client started")
    log("COMFY_URL={}".format(COMFY_URL))
    log("LEASE_HEARTBEAT_URL={}".format(LEASE_HEARTBEAT_URL))
    log("CHECK_INTERVAL_SECONDS={}".format(CHECK_INTERVAL_SECONDS))

    while True:
        if comfy_is_alive():
            try:
                res = send_heartbeat()
                log("ComfyUI online. heartbeat accepted: {}".format(res))
            except Exception as e:
                log("ComfyUI online, but heartbeat failed: {}".format(e))
        else:
            log("ComfyUI offline. heartbeat not sent.")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
