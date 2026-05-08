"""
Code Watcher — watches your codebase and proactively interrupts with advice.

FIXES (2026-05-08):
  - Code watcher no longer fires on startup scan (first-pass hashes only, no interrupt)
  - Only broadcasts when at least one WebSocket client is actually connected
  - Interrupt cooldown raised to 120s to avoid spamming
"""
import asyncio
import hashlib
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("jarvis.code_watcher")

# Patterns that trigger proactive interrupts
_SMELL_PATTERNS = [
    (re.compile(r'\bexcept\s*:', re.M),                   "bare except clause — you'll swallow every error including keyboard interrupts"),
    (re.compile(r'(password|secret|api_key)\s*=\s*["\'].+["\']', re.I), "hardcoded credential detected"),
    (re.compile(r'TODO|FIXME|HACK|XXX'),                   "unresolved TODO or FIXME"),
    (re.compile(r'for .+ in .+:\s*\n\s+for .+ in .+:'),   "nested loop — could be O(n²), worth checking"),
    (re.compile(r'time\.sleep\(\d+\)'),                    "blocking sleep in code — consider asyncio.sleep if async"),
    (re.compile(r'print\s*\('),                            "print statement in code — use logging instead"),
    (re.compile(r'eval\s*\('),                             "eval() is dangerous — consider safer alternatives"),
]

_CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".java", ".go", ".rs", ".cpp", ".c"}


class CodeWatcher:

    def __init__(
        self,
        on_interrupt: Callable[[str], None],
        llm_client: Any,
        speech_processor: Any,
        manager: Any,
    ):
        self.on_interrupt     = on_interrupt
        self.llm_client       = llm_client
        self.speech_processor = speech_processor
        self.manager          = manager

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Current context
        self._current_file: Optional[str] = None
        self._current_content: str = ""
        self._current_language: str = "python"
        self._cursor_line: int = 0
        self._file_hashes: dict[str, str] = {}

        # FIX: track whether first scan is done — never interrupt on startup
        self._initial_scan_done: bool = False

        # FIX: raised cooldown to 120s, and track per file to avoid hammering same file
        self._last_interrupt_time: float = 0
        self._interrupt_cooldown: float = 120.0

        logger.info("CodeWatcher initialised")

    def start(self):
        from app.config import settings
        if not settings.CODE_WATCH_ENABLED:
            logger.info("Code watcher disabled (CODE_WATCH_ENABLED=False)")
            return

        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(f"Code watcher started — watching {settings.CODE_WATCH_PATH}")

    def stop(self):
        self._running = False
        logger.info("Code watcher stopped")

    async def update_context(self, data: dict):
        """Called when UI or editor sends a code context update."""
        self._current_file     = data.get("file", self._current_file)
        self._current_content  = data.get("content", self._current_content)
        self._current_language = data.get("language", self._current_language)
        self._cursor_line      = data.get("cursor_line", self._cursor_line)
        logger.debug(f"Code context updated: {self._current_file} ({len(self._current_content)} chars)")

    def get_context_snippet(self, lines_around: int = 30) -> str:
        if not self._current_content:
            return ""
        lines = self._current_content.splitlines()
        if not lines:
            return ""
        cursor = max(0, self._cursor_line - 1)
        start  = max(0, cursor - lines_around)
        end    = min(len(lines), cursor + lines_around)
        snippet = "\n".join(lines[start:end])
        return (
            f"File: {self._current_file or 'unknown'} "
            f"(language: {self._current_language}, "
            f"showing lines {start+1}-{end})\n\n"
            f"```{self._current_language}\n{snippet}\n```"
        )

    # ── File system watching loop ───────────────────────────────────

    def _watch_loop(self):
        from app.config import settings
        watch_path = Path(settings.CODE_WATCH_PATH).expanduser()

        if not watch_path.exists():
            logger.warning(f"CODE_WATCH_PATH does not exist: {watch_path}")
            return

        logger.info(f"Watching: {watch_path}")

        while self._running:
            try:
                self._scan_directory(watch_path)
            except Exception as e:
                logger.error(f"Watch loop error: {e}")
            time.sleep(3)

    def _scan_directory(self, path: Path):
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _CODE_EXTENSIONS:
                continue
            if any(p.startswith(".") or p in ("node_modules", "__pycache__", ".venv", "venv", "dist", "build")
                   for p in file_path.parts):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                content_hash = hashlib.md5(content.encode()).hexdigest()
                path_str = str(file_path)
                old_hash = self._file_hashes.get(path_str)

                if old_hash != content_hash:
                    self._file_hashes[path_str] = content_hash
                    # FIX: only interrupt on REAL changes, not on first scan
                    if old_hash is not None and self._initial_scan_done:
                        self._on_file_changed(file_path, content)

            except Exception:
                pass

        # Mark first scan complete after first full pass
        if not self._initial_scan_done:
            self._initial_scan_done = True
            logger.info(f"Initial scan complete — {len(self._file_hashes)} files indexed, watching for changes")

    def _on_file_changed(self, file_path: Path, content: str):
        now = time.time()
        if now - self._last_interrupt_time < self._interrupt_cooldown:
            return

        # FIX: only interrupt if someone is actually connected
        if not self.manager.active:
            logger.debug("Code smell detected but no clients connected — skipping interrupt")
            return

        lang = self._guess_language(file_path)
        self._current_file     = str(file_path)
        self._current_content  = content
        self._current_language = lang

        findings = self._detect_smells(content)
        if findings:
            self._last_interrupt_time = now
            smell = findings[0]
            msg = f"Hey, I noticed something in {file_path.name} — {smell}. Want me to explain or suggest a fix?"
            logger.info(f"Code interrupt: {smell}")

            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._speak_and_broadcast(msg, file_path.name, smell),
                    self._loop
                )

    async def _speak_and_broadcast(self, message: str, filename: str, detail: str):
        """Synthesize the interrupt message and broadcast to UI."""
        # FIX: double-check clients still connected before synthesizing
        if not self.manager.active:
            return
        try:
            tts = await self.speech_processor.synthesize(message)
            payload = {
                "type": "code_interrupt",
                "content": message,
                "filename": filename,
                "detail": detail,
            }
            if tts.get("audio_data"):
                import base64
                payload["audio_b64"]    = base64.b64encode(tts["audio_data"]).decode()
                payload["audio_format"] = tts.get("format", "mp3")
            await self.manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Code interrupt speak error: {e}")

    def _detect_smells(self, content: str) -> list[str]:
        findings = []
        for pattern, message in _SMELL_PATTERNS:
            if pattern.search(content):
                findings.append(message)
        fn_lines = self._longest_function(content)
        if fn_lines > 40:
            findings.append(f"function is {fn_lines} lines — consider breaking it down")
        return findings

    def _longest_function(self, content: str) -> int:
        lines = content.splitlines()
        max_len = 0
        current_len = 0
        in_fn = False
        for line in lines:
            stripped = line.strip()
            if re.match(r'(def |async def |function |const .+ = .*(=>|\{)|public |private )', stripped):
                if current_len > max_len:
                    max_len = current_len
                current_len = 1
                in_fn = True
            elif in_fn:
                current_len += 1
        return max(max_len, current_len)

    def _guess_language(self, file_path: Path) -> str:
        ext_map = {
            ".py": "python", ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript", ".cs": "csharp",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".cpp": "cpp", ".c": "c",
        }
        return ext_map.get(file_path.suffix.lower(), "code")

    async def analyze_current_file(self, question: str = "") -> str:
        if not self._current_content:
            return "I don't have any code context yet. Open a file and start coding."
        question = question or "Review this code. Point out bugs, anti-patterns, and suggest improvements."
        prompt = (
            f"You are a senior software engineer reviewing {self._current_language} code.\n"
            f"Developer question: {question}\n\n"
            f"{self.get_context_snippet(50)}\n\n"
            "Be concise, specific, and actionable. Speak naturally."
        )
        result = await self.llm_client.generate_response(
            messages=[{"role": "user", "content": prompt}]
        )
        return result.get("content", "")

    async def suggest_approach(self, task_description: str) -> str:
        prompt = (
            f"A developer wants to: {task_description}\n\n"
            + (f"Current code context:\n{self.get_context_snippet(20)}\n\n" if self._current_content else "")
            + "Suggest 2-3 concrete approaches, explain the trade-offs briefly, "
            "and recommend the best one. Be direct and practical."
        )
        result = await self.llm_client.generate_response(
            messages=[{"role": "user", "content": prompt}]
        )
        return result.get("content", "")
