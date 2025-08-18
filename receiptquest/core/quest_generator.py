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
            "  \"objectives\": [\"Set a timer\", \"Close distractions\", \"Work on the next small chunk\", \"Write 1-2 summary sentences\"],\n"
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
        existing_block = ""
        if existing:
            try:
                steps_json = json.dumps([str(s) for s in existing])
            except Exception:
                steps_json = "[]"
            existing_block = ("UserProvidedSteps: " + steps_json + "\n")
        custom_instructions = self._load_custom_instructions()
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
        # Strong negative constraints for cleaning to avoid study bleed-through
        if category == "cleaning":
            rules.append(
                "Do not include any study terms: writing utensil, notebook, paper, page, skim, read, summary, problem."
            )
        rules_block = ("\n".join(rules) + "\n") if rules else ""
        return (
            "You produce a VERY granular, activation-friendly checklist for the user's real-life task.\n"
            "Identify the task category from the user's words (e.g., making coffee, washing dishes, doing laundry, cooking, studying, cleaning, showering, errands).\n"
            "Produce domain-appropriate steps for that task.\n"
            "Do NOT invent brand/model-specific details or people.\n"
            "Do NOT guess hidden specifics (no fake recipes, names, tools not mentioned).\n"
            "Avoid all times/durations (no minutes/seconds/timers).\n"
            "The FIRST step must be a tiny micro-activation that reduces friction.\n"
            "Use short imperative sentences (<= 60 chars).\n"
            "For beverages/liquids, end with 'Enjoy a sip' (never 'bite').\n"
            "If coffee method is unknown, write steps usable with common machines/pods. Avoid pour-over/manual specifics.\n"
            + ("Keep objectives between 6 and 9 steps.\n" if fast else "") +
            "Output STRICT JSON ONLY. No extra text, no markdown.\n"
            "Schema: {\n"
            "  \"title\": string,\n"
            "  \"description\": string,\n"
            "  \"objectives\": array of short strings (8–14 typical),\n"
            "  \"rewards\": string\n"
            "}\n"
            "Examples (task-aware, non-fabricated):\n"
            "{\n"
            "  \"title\": \"Make Bed\",\n"
            "  \"description\": \"Make a tidy bed.\",\n"
            "  \"objectives\": [\n"
            "    \"Clear items off the bed\", \"Shake out the sheets\", \"Fit the bottom sheet\",\n"
            "    \"Smooth out wrinkles\", \"Add the top sheet\", \"Pull up blanket or duvet\",\n"
            "    \"Arrange pillows\", \"Smooth the top layer\", \"Mark this as done\"\n"
            "  ],\n"
            "  \"rewards\": \"Tidy space and reset\"\n"
            "}\n"
            "{\n"
            "  \"title\": \"Tidy Desk\",\n"
            "  \"description\": \"Clear and reset a desk surface.\",\n"
            "  \"objectives\": [\n"
            "    \"Trash obvious wrappers\", \"Gather tools (bin, cloth)\", \"Make a clear spot\",\n"
            "    \"Group: keep / relocate / trash\", \"Wipe the desk\", \"Return keep items neatly\",\n"
            "    \"Relocate other items\", \"Put tools away\", \"Mark this as done\"\n"
            "  ],\n"
            "  \"rewards\": \"Clean space and reset\"\n"
            "}\n"
            "{\n"
            "  \"title\": \"Make Coffee\",\n"
            "  \"description\": \"Brew a simple cup of coffee.\",\n"
            "  \"objectives\": [\n"
            "    \"Put mug and tools on the counter\", \"Fill kettle with water\", \"Heat the water\",\n"
            "    \"Place filter and rinse it\", \"Add ground coffee\", \"Pour a little water to wet grounds\",\n"
            "    \"Pour remaining water slowly\", \"Wait for it to drip\", \"Discard filter\",\n"
            "    \"Add milk/sugar if desired\", \"Enjoy a sip\"\n"
            "  ],\n"
            "  \"rewards\": \"Warm drink and a small win\"\n"
            "}\n"
            "{\n"
            "  \"title\": \"Wash Dishes\",\n"
            "  \"description\": \"Clean a sink of dishes.\",\n"
            "  \"objectives\": [\n"
            "    \"Clear a small space by the sink\", \"Scrape food into trash\", \"Group dishes by type\",\n"
            "    \"Fill sink with warm soapy water\", \"Wash cups and utensils first\", \"Wash plates and bowls\",\n"
            "    \"Wash pots/pans last\", \"Rinse and rack to dry\", \"Wipe the counter\"\n"
            "  ],\n"
            "  \"rewards\": \"Clean space and reset\"\n"
            "}\n"
            + (custom_instructions + "\n" if custom_instructions else "")
            + category_block + rules_block + f"Task: {intent}\n" + existing_block +
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

    # --------- Two-stage planning helpers (model-agnostic, general-purpose) ---------
    def _extract_keywords(self, text: str) -> List[str]:
        raw = (text or "").lower()
        tokens = [t.strip(" ,.;:!?") for t in raw.split()]
        stop = {
            "the","a","an","and","or","then","after","that","to","of","for","on","in","at","with","from","into","by","it","is","be","do","did","done","make","take","quick","break","my","your","their","our","this","next","first","second","third","small","big","little","some","any"
        }
        keywords: List[str] = []
        for t in tokens:
            if len(t) <= 2 or t in stop:
                continue
            if t not in keywords:
                keywords.append(t)
        return keywords[:20]

    def _genericity_score(self, steps: List[str]) -> float:
        if not steps:
            return 1.0
        generic_phrases = [
            "open the task","first problem","next chunk","save","skim","review instructions",
            "complete the next section","work on it","start","continue","finish","wrap up",
            "plan","prepare","complete","do the task","task","thing"
        ]
        total = 0
        generic_hits = 0
        for s in steps:
            total += 1
            low = s.lower()
            if any(p in low for p in generic_phrases):
                generic_hits += 1
        return generic_hits / max(1, total)

    def _build_planner_prompt(self, intent: str) -> str:
        return (
            "You are a planning assistant. Extract a concrete action plan for the user's task.\n"
            "Do NOT invent specific brands or people. Use only nouns present in the task or generic nouns.\n"
            "Output STRICT JSON ONLY with keys: {\"domain\": string, \"items\": string[], \"subtasks\": string[]}.\n"
            "- domain: one of: cleaning, study, cooking, beverage, laundry, dishes, hygiene, admin, workout, errand, generic.\n"
            "- items: 2-6 generic items actually needed (e.g., bin, cloth, mug, kettle, pen, notebook).\n"
            "- subtask names: 2-4 short labels describing parts of the task (e.g., clear surface, wipe, reset).\n"
            f"Task: {intent}\n"
            "Respond with JSON only."
        )

    def _build_steps_from_plan_prompt(self, intent: str, plan_json: str, fast: bool) -> str:
        speed_note = "Keep between 6 and 9 steps." if fast else "Use 8–14 steps."
        return (
            "You create a VERY granular, activation-friendly checklist from the user's task and a simple plan.\n"
            "Rules:\n"
            "- First step = micro-activation (clear space, put phone away, place item).\n"
            "- Use short imperative sentences (<= 50 chars).\n"
            "- No times/durations (no minutes/seconds/timers).\n"
            "- Use only nouns from the task or these plan 'items'; otherwise use generic nouns (tools, materials).\n"
            "- Do NOT invent brands or people; no exclamation marks.\n"
            f"- {speed_note}\n"
            "- End beverages with 'Enjoy a sip'.\n"
            "Output STRICT JSON ONLY with keys: {\"title\": string, \"description\": string, \"objectives\": string[], \"rewards\": string}.\n"
            f"Task: {intent}\n"
            f"Plan: {plan_json}\n"
            "Respond with JSON only."
        )

    def _is_fast(self, fast_flag: Optional[bool]) -> bool:
        env_fast = os.getenv("RQS_FAST")
        if isinstance(fast_flag, bool):
            return fast_flag
        if isinstance(env_fast, str) and env_fast.strip().lower() in {"1", "true", "yes", "on"}:
            return True
        return False

    def _postprocess_objectives(self, intent: str, objectives: List[str]) -> List[str]:
        text = (intent or "").lower()
        beverage_words = ["coffee", "tea", "drink", "beverage", "water"]
        is_beverage = any(w in text for w in beverage_words)
        is_cleaning = any(k in text for k in ["tidy", "declutter", "organize", "clean", "wipe", "dust", "desk", "table", "counter"])
        is_bed = any(w in text for w in ["make bed", "make the bed", "bed", "duvet", "pillow", "bedsheet", "bed sheet"]) and "bedroom" not in text
        is_study = any(w in text for w in ["study", "homework", "assignment", "classwork", "read"]) or any(w in text for w in ["math", "english"]) 
        is_math = any(w in text for w in ["math", "algebra", "geometry", "calculus", "statistics"]) and ("homework" in text or "math" in text)
        is_english = any(w in text for w in ["english", "essay", "paper", "writing"]) and ("homework" in text or "english" in text)
        cleaned: List[str] = []
        for o in objectives:
            s = str(o)
            low = s.lower()
            if is_beverage and "bite" in low:
                s = s.replace("bite", "sip").replace("Bite", "Sip")
            if is_cleaning and any(w in low for w in ["writing", "notebook", "paper", "page", "skim", "problem", "summary", "read"]):
                # Replace study-ish bleed with cleaning-friendly phrasing
                s = "Clear a small surface"
            cleaned.append(s)
        # De-duplicate while preserving order
        seen = set()
        unique: List[str] = []
        for s in cleaned:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        if is_bed:
            return [
                "Clear items off the bed",
                "Shake out the sheets",
                "Fit the bottom sheet",
                "Smooth out wrinkles",
                "Add the top sheet",
                "Pull up blanket or duvet",
                "Arrange pillows",
                "Smooth the top layer",
                "Mark this as done",
            ]
        # If study set looks too generic, replace with structured flow
        generic_tokens = {"open the task", "open to the right page", "first problem", "next chunk", "save", "skim"}
        too_generic = sum(1 for s in unique for t in generic_tokens if t in s.lower()) >= max(2, len(unique)//3)
        if is_study and (too_generic or len(unique) < 6):
            if is_math:
                return [
                    "Grab a pencil and notebook",
                    "Clear a small space",
                    "Take homework out",
                    "Open to the right page",
                    "Skim instructions",
                    "Do the first problem",
                    "Check answer quickly",
                    "Do the next 2 problems",
                    "Write a 1-sentence plan if stuck",
                    "Save your work",
                    "Put materials away",
                    "Mark this as done",
                ]
            if is_english:
                return [
                    "Grab a pen and notebook",
                    "Clear a small space",
                    "Open the assignment",
                    "Skim the prompt",
                    "Write one starter sentence",
                    "Draft the next small section",
                    "Quick read and adjust",
                    "Save your work",
                    "Put materials away",
                    "Mark this as done",
                ]
        return unique

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
