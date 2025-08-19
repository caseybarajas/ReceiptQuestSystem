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

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None) -> None:
        # Allow environment overrides for model and base URL
        env_model = os.getenv("RQS_MODEL")
        env_url = os.getenv("RQS_OLLAMA_URL")
        # Default to a very small, fast model for low-spec devices
        self.model = (model or env_model or "qwen2:0.5b").strip()
        self.base_url = (base_url or env_url or "http://127.0.0.1:11434").rstrip("/")

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
    # Define constant for consistent top_p across all generation modes
    DEFAULT_TOP_P = 0.9
    
    def _request(self, prompt: str, options: Optional[Dict[str, Any]] = None, timeout_s: int = 60) -> str:
        default_options: Dict[str, Any] = {
            "temperature": 0.2,
            "top_p": self.DEFAULT_TOP_P,
            "num_predict": 350,
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
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
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
            "  \"objectives\": [\"Prepare workspace\", \"Close distractions\", \"Work on the next small chunk\", \"Write 1-2 summary sentences\"],\n"
            "  \"rewards\": \"+10 Momentum, +10 Satisfaction\"\n"
            "}\n"
            f"Task: {intent}\n"
            "Respond with JSON only."
        )

    def _build_granular_prompt(
        self,
        intent: str,
        existing: Optional[List[str]] = None,
        fast: bool = False,
        category_override: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> str:
        # Include any existing user-provided steps
        existing_block = ""
        if existing:
            try:
                steps_json = json.dumps([str(s) for s in existing])
            except Exception:
                steps_json = "[]"
            existing_block = "UserProvidedSteps: " + steps_json + "\n"

        # Optional custom instructions
        custom_instructions = self._load_custom_instructions()
        custom_block = (custom_instructions.strip() + "\n") if custom_instructions else ""

        # Lightweight categorization to reduce misclassification (e.g., tidy desk ≠ study)
        def _infer_category(text: str) -> Dict[str, Any]:
            t = (text or "").lower()
            info: Dict[str, Any] = {"category": "generic"}
            if any(k in t for k in ["tidy", "declutter", "organize", "clean", "wipe", "dust"]):
                info["category"] = "cleaning"
                for surf in ["desk", "table", "counter", "room", "kitchen", "bathroom"]:
                    if surf in t:
                        info["surface"] = surf
                        break
                return info
            if any(k in t for k in ["coffee", "tea", "brew", "drink", "beverage"]):
                info["category"] = "beverage"
                return info
            if any(k in t for k in ["study", "homework", "assignment", "write", "essay", "notes", "reading"]):
                info["category"] = "study"
                return info
            if any(k in t for k in ["dishes", "sink", "dishwasher", "plates", "cups"]):
                info["category"] = "dishes"
                return info
            if any(k in t for k in ["laundry", "washer", "dryer", "clothes", "fold"]):
                info["category"] = "laundry"
                return info
            if any(k in t for k in ["cook", "cooking", "meal", "breakfast", "lunch", "dinner", "prep"]):
                info["category"] = "cooking"
                return info
            if any(k in t for k in ["shower", "bathe", "bath", "wash hair"]):
                info["category"] = "hygiene"
                return info
            if any(k in t for k in ["email", "inbox", "admin", "forms", "bills", "tax", "bank"]):
                info["category"] = "admin"
                return info
            if any(k in t for k in ["workout", "exercise", "gym", "walk", "run", "stretch", "pushup", "yoga"]):
                info["category"] = "workout"
                return info
            if any(k in t for k in ["grocery", "shopping", "store", "errand", "pharmacy"]):
                info["category"] = "errand"
                return info
            return info

        if isinstance(category_override, str) and category_override.strip():
            category = category_override.strip().lower()
            surface = ""
        else:
            ctx = _infer_category(intent)
            category = ctx.get("category", "generic")
            surface = ctx.get("surface", "")
        category_block = f"Category: {category}\n" + (f"Surface: {surface}\n" if surface else "")

        # Category-specific rules
        rules: List[str] = []
        if category == "cleaning":
            rules += [
                "Avoid study/homework actions (no reading or writing).",
                "Use a cleaning flow: declutter, group, wipe, reset.",
            ]
        if category == "study":
            rules += [
                "Avoid cleaning actions (no wiping or washing).",
                "Use a study flow: open task, first problem, next chunk, save.",
            ]
            if isinstance(subject, str):
                subj = subject.strip().lower()
                if subj == "math":
                    rules.append("Use math wording: problem, check answer, next 1–2 problems.")
                if subj == "english":
                    rules.append("Use writing wording: draft a sentence, next small section, quick read.")
        if category == "beverage":
            rules += [
                "End with 'Enjoy a sip'.",
                "Use machine/pod-friendly steps unless a method is stated.",
            ]
        if category == "cleaning":
            rules.append(
                "Do not include any study terms: writing utensil, notebook, paper, page, skim, read, summary, problem."
            )
        rules_block = ("\n".join(rules) + "\n") if rules else ""

        prompt_text = (
            custom_block
            + "You produce a VERY granular, activation-friendly checklist for the user's real-life task.\n"
            + "Identify the task category from the user's words (e.g., making coffee, washing dishes, doing laundry, cooking, studying, cleaning, showering, errands).\n"
            + "Produce domain-appropriate steps for that task.\n"
            + "Do NOT invent brand/model-specific details or people.\n"
            + "Do NOT guess hidden specifics (no fake recipes, names, tools not mentioned).\n"
            + "Avoid all times/durations (no minutes/seconds/timers).\n"
            + "The FIRST step must be a tiny micro-activation that reduces friction.\n"
            + "Use short imperative sentences (<= 60 chars).\n"
            + "For beverages/liquids, end with 'Enjoy a sip' (never 'bite').\n"
            + category_block
            + rules_block
            + existing_block
            + "Output STRICT JSON ONLY. No extra text, no markdown.\n"
            + "Schema: {\n  \"title\": string,\n  \"description\": string,\n  \"objectives\": array of 6-15 short strings,\n  \"rewards\": string\n}\n"
            + f"Task: {intent}\n"
            + "Respond with JSON only."
        )
        return prompt_text

    def generate(self, intent: str, fast: Optional[bool] = None) -> Dict[str, object]:
        # Ensure server and model are available
        self.ensure_model_ready()
        is_fast = self._is_fast(fast)
        # Two-stage planning: plan → steps; robust fallback to single-pass
        try:
            planner_prompt = self._build_planner_prompt(intent)
            plan_text = self._request(planner_prompt, options={"temperature": 0.1, "top_p": self.DEFAULT_TOP_P, "num_predict": 160}, timeout_s=20 if is_fast else 35)
            # validate plan as JSON
            plan_obj = json.loads(plan_text)
            # derive domain for post-processing hints
            domain = str(plan_obj.get("domain", "generic")).strip().lower()
            steps_prompt = self._build_steps_from_plan_prompt(intent, json.dumps(plan_obj), is_fast)
            text = self._request(steps_prompt, options={"temperature": 0.1 if is_fast else 0.2, "top_p": self.DEFAULT_TOP_P, "num_predict": 280 if is_fast else 420}, timeout_s=30 if is_fast else 60)
        except Exception:
            prompt = self._build_prompt(intent)
            text = self._request(prompt, options={"temperature": 0.1 if is_fast else 0.2, "top_p": self.DEFAULT_TOP_P, "num_predict": 220 if is_fast else 350}, timeout_s=30 if is_fast else 60)
        # Best effort to parse JSON; if it fails, fallback to simple structure
        def _extract_json_object(s: str) -> Optional[Dict[str, Any]]:
            # Try direct parse first
            try:
                return json.loads(s)
            except Exception:
                pass
            # Scan for JSON object candidates and use raw_decode to avoid brace-counting inside strings
            decoder = json.JSONDecoder()
            i = 0
            length = len(s)
            while i < length:
                start = s.find('{', i)
                if start == -1:
                    break
                try:
                    obj, end = decoder.raw_decode(s, start)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    # Not a valid object at this position; continue searching
                    pass
                i = start + 1
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
            objectives = self._postprocess_objectives(intent, objectives)
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

    def generate_granular(
        self,
        intent: str,
        existing_objectives: Optional[List[str]] = None,
        fast: Optional[bool] = None,
        category_override: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> Dict[str, object]:
        self.ensure_model_ready()
        is_fast = self._is_fast(fast)
        prompt = self._build_granular_prompt(
            intent,
            existing_objectives,
            fast=is_fast,
            category_override=category_override,
            subject=subject,
        )
        opts = {"temperature": 0.1, "top_p": self.DEFAULT_TOP_P, "num_predict": 350 if is_fast else 700}
        text = self._request(prompt, options=opts, timeout_s=30 if is_fast else 60)
        # Parse like in generate()
        def _extract_json_object(s: str) -> Optional[Dict[str, Any]]:
            # Try direct parse first
            try:
                return json.loads(s)
            except Exception:
                pass
            # Use raw_decode scanning from each '{'
            decoder = json.JSONDecoder()
            i = 0
            length = len(s)
            while i < length:
                start = s.find('{', i)
                if start == -1:
                    break
                try:
                    obj, end = decoder.raw_decode(s, start)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    pass
                i = start + 1
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
            objectives = self._postprocess_objectives(intent, objectives)
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
