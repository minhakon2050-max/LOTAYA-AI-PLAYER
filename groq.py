import os
import json
import urllib.request
import urllib.error

def ask_groq(message):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return "API KEY NOT FOUND"

    data = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": "You are LOTAYA AI."},
            {"role": "user", "content": message}
        ]
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
            "User-Agent": "LOTAYA-AI/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read().decode())
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return "HTTP " + str(e.code) + ": " + e.read().decode()
    except Exception as e:
        return str(e)
