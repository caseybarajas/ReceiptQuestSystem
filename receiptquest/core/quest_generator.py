from typing import List, Dict, Any
import json
import urllib.request
import urllib.error
import time
from typing import Optional
import os


class LocalLLMQuestGenerator:
    """Generate a quest from a short user intent using a local Ollama server.

    This expects an Ollama-compatible HTTP server running on localhost:11434.
    Default model is a small, fast one (e.g., 'qwen2:0.5b' or 'phi3:mini').
    """

    def __init__(self, model: str = "phi3:mini", base_url: str = "http://127.0.0.1:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    # -------- HTTP helpers --------
    def _get_json(self, path: str, timeout: float = 5.0) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path: str, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post_stream(self, path: str, payload: Dict[str, Any], timeout: float = 600.0):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    # -------- Ollama readiness --------
    def is_server_running(self) -> bool:
        try:
            _ = self._get_json("/api/tags", timeout=2.0)
            return True
        except Exception:
            return False

    def model_is_available(self) -> bool:
        try:
            tags = self._get_json("/api/tags", timeout=5.0)
            for m in tags.get("models", []) or []:
                name = str(m.get("name", ""))
                if name.lower() == self.model.lower():
                    return True
            return False
        except Exception:
            return False

    def pull_model(self, progress: bool = True) -> None:
        if progress:
            print(f"Preparing local model '{self.model}' (this may take a minute)...")
        try:
            # Stream progress until completion
            with self._post_stream("/api/pull", {"name": self.model}, timeout=1800.0) as resp:
                for raw_line in resp:
                    try:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        j = json.loads(line)
                        status = j.get("status") or j.get("error")
                        if progress and status:
                            print(f"- {status}")
                        # Some responses include "completed": true at the end
                        if j.get("completed") is True or (isinstance(status, str) and status.lower() in {"success", "pulled"}):
                            break
                    except Exception:
                        # ignore individual parse errors and continue streaming
                        continue
        except urllib.error.HTTPError as e:
            # 200 with stream is typical; if server returns error use message
            raise RuntimeError(f"Model pull failed: HTTP {e.code} {e.reason}")
        except Exception as e:
            raise RuntimeError(f"Model pull failed: {e}")

    def ensure_model_ready(self) -> None:
        if not self.is_server_running():
            raise RuntimeError("Ollama server is not running at 127.0.0.1:11434. Start it with 'ollama serve'.")
        if not self.model_is_available():
            self.pull_model(progress=True)
            # Verify after pull
            # small backoff; registry updates can be slightly delayed
            for _ in range(5):
                if self.model_is_available():
                    break
                time.sleep(1.0)
            if not self.model_is_available():
                raise RuntimeError(f"Model '{self.model}' is not available after pull.")

    # -------- Generation --------
    def _request(self, prompt: str, options: Optional[Dict[str, Any]] = None) -> str:
        default_options: Dict[str, Any] = {
            "temperature": 0.2,
            "num_predict": 300,
        }
        if isinstance(options, dict):
            request_options = {**default_options, **options}
        else:
            request_options = default_options
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": request_options,
        }
        data = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/api/generate"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "").strip()
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 300,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "").strip()

    def _build_prompt(self, intent: str) -> str:
        return (
            "You are an assistant that converts a user's real-life task into a neutral, generic, step-by-step plan.\n"
            "Do NOT invent specific books, tools, people, or topics not explicitly mentioned. Stay generic and process-oriented.\n"
            "If the task is ambiguous (e.g., 'do math homework'), do NOT guess a subject, topic, chapter, or page. Keep wording generic (e.g., 'open to the right page', 'do the first problem').\n"
            "Do NOT include times, durations, timers, or any time-like tokens: minute(s), min, second(s), sec, 20min, 5-min, clock, countdown, timer, schedule at X, 3–5, 30s, etc.\n"
            "Output STRICT JSON ONLY. No extra text, no markdown.\n"
            "Schema: {\n"
            "  \"title\": string,\n"
            "  \"description\": string,\n"
            "  \"objectives\": array of 2-5 short strings,\n"
            "  \"rewards\": string\n"
            "}\n"
            "Examples (showing generic, non-fabricated steps):\n"
            "{\n"
            "  \"title\": \"English Homework\",\n"
            "  \"description\": \"Make concrete progress on English homework.\",\n"
            "  \"objectives\": [\"Gather materials\", \"Review assignment instructions\", \"Complete the next section\", \"Proofread and save\"],\n"
            "  \"rewards\": \"+10 Momentum, +10 Satisfaction\"\n"
            "}\n"
            "{\n"
            "  \"title\": \"Study Session\",\n"
            "  \"description\": \"Focused study session with clear start and stop.\",\n"
            "  \"objectives\": [\"Set a timer\", \"Close distractions\", \"Work on the next small chunk\", \"Write 1-2 summary sentences\"],\n"
            "  \"rewards\": \"+10 Momentum, +10 Satisfaction\"\n"
            "}\n"
            f"Task: {intent}\n"
            "Respond with JSON only."
        )

    def _build_granular_prompt(self, intent: str, existing: Optional[List[str]] = None) -> str:
        existing_block = ""
        if existing:
            # Provide user-provided steps to expand
            try:
                steps_json = json.dumps([str(s) for s in existing])
            except Exception:
                steps_json = "[]"
            existing_block = (
                "UserProvidedSteps: " + steps_json + "\n"
            )
        custom_instructions = self._load_custom_instructions()
        return (
            "You produce a VERY granular, activation-friendly checklist for the user's real-life task.\n"
            "Do NOT invent specifics (books, topics, brands, people) not explicitly provided.\n"
            "If the task is ambiguous (e.g., 'do math homework'), do NOT guess a subject, topic, chapter, or page. Keep wording generic (e.g., 'open to the right page', 'do the first problem').\n"
            "Do NOT include times, durations, timers, or minute/second counts in any step.\n"
            "Keep steps generic and process-oriented. Include micro-activation steps (e.g., clear space, put phone away, sip water). The FIRST objective should be a tiny micro-activation that reduces friction to start.\n"
            "Use short imperative sentences (<= 60 chars each).\n"
            "Output STRICT JSON ONLY. No extra text, no markdown.\n"
            "Schema: {\n"
            "  \"title\": string,\n"
            "  \"description\": string,\n"
            "  \"objectives\": array of short strings (use as many as necessary; 8–14 typical),\n"
            "  \"rewards\": string\n"
            "}\n"
            "Examples (non-fabricated):\n"
            "{\n"
            "  \"title\": \"Math Homework\",\n"
            "  \"description\": \"Make concrete progress on math homework.\",\n"
            "  \"objectives\": [\n"
            "    \"Grab a writing utensil\", \"Gather notebook and paper\", \"Clear a small space\",\n"
            "    \"Open to the right page\", \"Skim instructions\", \"Do the first problem\",\n"
            "    \"Sip water\", \"Do the next 2–3 problems\", \"Check answers quickly\",\n"
            "    \"Save your work\", \"Put materials back\", \"Mark this as done\"\n"
            "  ],\n"
            "  \"rewards\": \"+10 Momentum, +10 Satisfaction\"\n"
            "}\n"
            + (custom_instructions + "\n" if custom_instructions else "")
            + f"Task: {intent}\n" + existing_block +
            "Respond with JSON only."
        )

    def _load_custom_instructions(self) -> str:
        path = os.getenv("RQS_AI_INSTRUCTIONS_PATH", "ai_instructions.md")
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
                return text
        except Exception:
            return ""

    def generate(self, intent: str) -> Dict[str, object]:
        # Ensure server and model are available
        self.ensure_model_ready()
        prompt = self._build_prompt(intent)
        text = self._request(prompt)
        # Best effort to parse JSON; if it fails, fallback to simple structure
        def _extract_json_object(s: str) -> Optional[Dict[str, Any]]:
            # Direct parse first
            try:
                return json.loads(s)
            except Exception:
                pass
            # Find first balanced {...}
            start = s.find('{')
            while start != -1:
                depth = 0
                for i in range(start, len(s)):
                    ch = s[i]
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            candidate = s[start:i+1]
                            try:
                                return json.loads(candidate)
                            except Exception:
                                break
                start = s.find('{', start + 1)
            return None

        try:
            data_obj = _extract_json_object(text) or {}
            if not data_obj:
                raise ValueError("no json object found")
            data = data_obj
            title = str(data.get("title", "Untitled Quest")).strip() or "Untitled Quest"
            description = str(data.get("description", "")).strip()
            raw_objectives = data.get("objectives", [])
            if not isinstance(raw_objectives, list):
                raw_objectives = []
            objectives: List[str] = [str(x).strip() for x in raw_objectives if str(x).strip()]
            rewards = str(data.get("rewards", "")).strip()
            return {
                "title": title,
                "description": description,
                "objectives": objectives,
                "rewards": rewards,
            }
        except Exception:
            # Minimal fallback if model returned non-JSON text
            return {
                "title": "Untitled Quest",
                "description": intent.strip(),
                "objectives": [],
                "rewards": "+10 Motivation",
            }

    def generate_granular(self, intent: str, existing_objectives: Optional[List[str]] = None) -> Dict[str, object]:
        self.ensure_model_ready()
        prompt = self._build_granular_prompt(intent, existing_objectives)
        text = self._request(prompt, options={"temperature": 0.1, "top_p": 0.8})
        # Parse like in generate()
        def _extract_json_object(s: str) -> Optional[Dict[str, Any]]:
            try:
                return json.loads(s)
            except Exception:
                pass
            start = s.find('{')
            while start != -1:
                depth = 0
                for i in range(start, len(s)):
                    ch = s[i]
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            candidate = s[start:i+1]
                            try:
                                return json.loads(candidate)
                            except Exception:
                                break
                start = s.find('{', start + 1)
            return None
        try:
            data_obj = _extract_json_object(text) or {}
            if not data_obj:
                raise ValueError("no json object found")
            data = data_obj
            title = str(data.get("title", "Untitled Quest")).strip() or "Untitled Quest"
            description = str(data.get("description", "")).strip()
            raw_objectives = data.get("objectives", [])
            if not isinstance(raw_objectives, list):
                raw_objectives = []
            objectives: List[str] = [str(x).strip() for x in raw_objectives if str(x).strip()]
            rewards = str(data.get("rewards", "+10 Momentum, +10 Satisfaction")).strip()
            return {
                "title": title,
                "description": description,
                "objectives": objectives,
                "rewards": rewards,
            }
        except Exception:
            # Failure: return minimal shell; caller can fallback
            return {
                "title": "Untitled Quest",
                "description": intent.strip(),
                "objectives": [],
                "rewards": "+10 Momentum, +10 Satisfaction",
            }
