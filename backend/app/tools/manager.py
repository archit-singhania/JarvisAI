"""
Tool Manager — plugin-style registry.
Every tool is a function registered with @tool_registry.register("name").
The LLM orchestrator calls execute(tool_name, user_input) automatically.
"""
import logging
import random
import subprocess
import platform
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("jarvis.tools")


# ------------------------------------------------------------------ #
#  Registry                                                            #
# ------------------------------------------------------------------ #

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._keywords: Dict[str, list[str]] = {}

    def register(self, name: str, keywords: list[str]):
        """Decorator to register a tool with trigger keywords."""
        def decorator(fn: Callable):
            self._tools[name] = fn
            self._keywords[name] = keywords
            logger.info(f"Tool registered: {name}")
            return fn
        return decorator

    def detect(self, user_input: str) -> Optional[str]:
        """Return the first tool name whose keywords match the input."""
        lower = user_input.lower()
        for name, kws in self._keywords.items():
            if any(kw in lower for kw in kws):
                return name
        return None

    async def execute(self, tool_name: str, user_input: str) -> Dict[str, Any]:
        if tool_name not in self._tools:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
        try:
            result = await self._tools[tool_name](user_input)
            return {"success": True, "tool": tool_name, "result": result}
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            return {"success": False, "tool": tool_name, "error": str(e)}


tool_registry = ToolRegistry()


# ------------------------------------------------------------------ #
#  Built-in Tools                                                      #
# ------------------------------------------------------------------ #

@tool_registry.register("time", keywords=["time", "what time", "current time", "date", "today"])
async def get_time(_: str) -> str:
    now = datetime.now()
    return f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d %Y')}."


@tool_registry.register("weather", keywords=["weather", "temperature", "forecast", "raining", "sunny"])
async def get_weather(user_input: str) -> str:
    """Free weather via Open-Meteo (no API key required)."""
    import httpx
    try:
        # Default Delhi coords — TODO: make location configurable
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 28.6139, "longitude": 77.2090,
                    "current_weather": True,
                    "hourly": "precipitation_probability",
                },
                timeout=5,
            )
        data = r.json()
        cw = data["current_weather"]
        code = cw["weathercode"]
        temp = cw["temperature"]
        wind = cw["windspeed"]
        desc = _weather_code(code)
        return f"Current weather: {desc}, {temp}°C, wind {wind} km/h."
    except Exception as e:
        return f"Couldn't fetch weather right now: {e}"


def _weather_code(code: int) -> str:
    mapping = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
               45: "Foggy", 61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
               80: "Rain showers", 95: "Thunderstorm"}
    return mapping.get(code, f"Weather code {code}")


@tool_registry.register("open_app", keywords=["open ", "launch ", "start chrome", "start spotify",
                                               "open chrome", "open spotify", "open notepad",
                                               "open calculator", "open terminal"])
async def open_app(user_input: str) -> str:
    lower = user_input.lower()
    os_name = platform.system()

    app_map_windows = {
        "chrome": "start chrome",
        "spotify": "start spotify",
        "notepad": "notepad",
        "calculator": "calc",
        "terminal": "start cmd",
        "vs code": "code",
        "vscode": "code",
        "explorer": "explorer",
    }
    app_map_mac = {
        "chrome": "open -a 'Google Chrome'",
        "spotify": "open -a Spotify",
        "terminal": "open -a Terminal",
        "vs code": "open -a 'Visual Studio Code'",
        "vscode": "open -a 'Visual Studio Code'",
        "finder": "open -a Finder",
    }

    mapping = app_map_windows if os_name == "Windows" else app_map_mac
    for key, cmd in mapping.items():
        if key in lower:
            subprocess.Popen(cmd, shell=True)
            return f"Opening {key.title()} for you."

    return "I couldn't identify which app to open. Try saying the app name more clearly."


@tool_registry.register("rap", keywords=["rap", "spit bars", "freestyle", "rhyme", "give me bars"])
async def rap_for_me(user_input: str) -> str:
    """Ask the LLM to write a short rap — returns lyrics for TTS to speak with rhythm."""
    # Extract topic from input
    lower = user_input.lower()
    for word in ["rap", "about", "on", "for", "freestyle"]:
        lower = lower.replace(word, "")
    topic = lower.strip() or "life and hustle"

    # This result gets passed back to LLM with a rap persona prompt
    return (
        f"[RAP_MODE topic='{topic}'] "
        "Generate a 4-bar rap verse with rhyming couplets, "
        f"about '{topic}'. Keep it punchy, witty, and rhythmic. "
        "Format: line 1 / line 2 / line 3 / line 4. No intro text."
    )


@tool_registry.register("sing", keywords=["sing", "sing a song", "hum", "song for me"])
async def sing_for_me(user_input: str) -> str:
    lower = user_input.lower()
    for word in ["sing", "a song", "about", "for me"]:
        lower = lower.replace(word, "")
    topic = lower.strip() or "sunshine and good vibes"
    return (
        f"[SING_MODE topic='{topic}'] "
        "Write short original song lyrics (verse + chorus) "
        f"about '{topic}'. Make it melodic and expressive. "
        "Format clearly with Verse and Chorus labels."
    )


@tool_registry.register("joke", keywords=["joke", "make me laugh", "funny", "tell me something funny"])
async def tell_joke(_: str) -> str:
    jokes = [
        "Why don't scientists trust atoms? Because they make up everything.",
        "I told my computer I needed a break. Now it won't stop sending me Kit-Kat ads.",
        "Why did the developer quit? Because they didn't get arrays.",
        "I'm reading a book on anti-gravity. It's impossible to put down.",
    ]
    return random.choice(jokes)


@tool_registry.register("search", keywords=["search for", "look up", "google", "find information about",
                                             "what is", "who is", "define"])
async def web_search(user_input: str) -> str:
    """DuckDuckGo instant answer — no API key required."""
    import httpx
    query = user_input
    for word in ["search for", "look up", "google", "find information about"]:
        query = query.lower().replace(word, "").strip()

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=5,
            )
        data = r.json()
        abstract = data.get("AbstractText") or data.get("Answer") or ""
        if abstract:
            return abstract[:400]
        return f"I searched for '{query}' but couldn't find a quick answer. Try asking me differently."
    except Exception as e:
        return f"Search failed: {e}"


@tool_registry.register("reminder", keywords=["remind me", "set a reminder", "alarm", "set alarm",
                                               "remind", "don't let me forget"])
async def set_reminder(user_input: str) -> str:
    """Saves reminder to SQLite. A background scheduler (Phase 3) will trigger it."""
    import sqlite3, re
    from pathlib import Path

    db_path = Path(__file__).parent.parent.parent.parent / "data" / "reminders.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS reminders
                    (id INTEGER PRIMARY KEY, text TEXT, created_at TEXT, triggered INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO reminders (text, created_at) VALUES (?, ?)",
                 (user_input, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    return f"Got it! I've saved your reminder: \"{user_input.strip()}\". (Full alarm scheduling coming in Phase 3)"


# ------------------------------------------------------------------ #
#  Manager (used by Orchestrator)                                      #
# ------------------------------------------------------------------ #

class ToolManager:
    """Thin wrapper so the orchestrator doesn't import tool_registry directly."""

    async def detect_and_execute(self, user_input: str):
        tool_name = tool_registry.detect(user_input)
        if tool_name:
            return await tool_registry.execute(tool_name, user_input)
        return None

    async def execute(self, tool_name: str, user_input: str):
        return await tool_registry.execute(tool_name, user_input)
