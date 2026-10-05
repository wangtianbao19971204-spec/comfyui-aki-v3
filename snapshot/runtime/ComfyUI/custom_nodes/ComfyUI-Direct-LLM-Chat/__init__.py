import json
import urllib.request
import urllib.error


class DirectLLMChat:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": (
                    "STRING",
                    {
                        "default": "http://127.0.0.1:8000/v1",
                        "multiline": False,
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                    },
                ),
                "model": (
                    "STRING",
                    {
                        "default": "your-model-name",
                        "multiline": False,
                    },
                ),
                "system_prompt": (
                    "STRING",
                    {
                        "default": "You are a direct chat assistant. Answer the current user message only. Do not rewrite the full request.",
                        "multiline": True,
                    },
                ),
                "chat_history": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
                "user_message": (
                    "STRING",
                    {
                        "default": "只回复 OK",
                        "multiline": True,
                    },
                ),
                "temperature": (
                    "FLOAT",
                    {
                        "default": 0.3,
                        "min": 0.0,
                        "max": 2.0,
                        "step": 0.05,
                    },
                ),
                "max_tokens": (
                    "INT",
                    {
                        "default": 1200,
                        "min": 1,
                        "max": 32768,
                        "step": 1,
                    },
                ),
                "timeout": (
                    "INT",
                    {
                        "default": 180,
                        "min": 10,
                        "max": 1800,
                        "step": 10,
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("answer", "next_history", "raw_json")
    FUNCTION = "run"
    CATEGORY = "LLM/Direct"

    def run(
        self,
        base_url,
        api_key,
        model,
        system_prompt,
        chat_history,
        user_message,
        temperature,
        max_tokens,
        timeout,
    ):
        base_url = base_url.strip().rstrip("/")
        api_key = api_key.strip()
        model = model.strip()
        system_prompt = system_prompt.strip()
        chat_history = chat_history.strip()
        user_message = user_message.strip()

        if not base_url:
            return ("ERROR: base_url is empty.", chat_history, "")

        if not model:
            return ("ERROR: model is empty.", chat_history, "")

        if not user_message:
            return ("ERROR: user_message is empty.", chat_history, "")

        messages = []

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt,
            })

        if chat_history:
            messages.append({
                "role": "user",
                "content": "CHAT_HISTORY:\n" + chat_history,
            })

        messages.append({
            "role": "user",
            "content": user_message,
        })

        payload = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            url=f"{base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=int(timeout)) as response:
                body = response.read().decode("utf-8", errors="replace")

            result = json.loads(body)

            answer = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            if not answer:
                answer = str(result)

            next_history_parts = []

            if chat_history:
                next_history_parts.append(chat_history)

            next_history_parts.append("User:\n" + user_message)
            next_history_parts.append("Assistant:\n" + answer)

            next_history = "\n\n".join(next_history_parts)

            return (
                answer,
                next_history,
                json.dumps(result, ensure_ascii=False, indent=2),
            )

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            error_text = f"HTTP ERROR {e.code}:\n{err_body}"
            return (error_text, chat_history, err_body)

        except Exception as e:
            error_text = f"ERROR:\n{repr(e)}"
            return (error_text, chat_history, "")


NODE_CLASS_MAPPINGS = {
    "DirectLLMChat": DirectLLMChat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DirectLLMChat": "Direct LLM Chat / CMD-style API Call",
}