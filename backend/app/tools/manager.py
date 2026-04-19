"""
Tool Manager — plugin registry.
All location data comes from settings (configured via .env).
No hardcoded values.
"""
import logging
import random
import subprocess
import platform
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("jarvis.tools")


# ── Registry ──────────────────────────────────────────────────────

class ToolRegistry:
    def __init__(self):
        self._tools:    Dict[str, Callable] = {}
        self._keywords: Dict[str, list[str]] = {}

    def register(self, name: str, keywords: list[str]):
        def decorator(fn: Callable):
            self._tools[name]    = fn
            self._keywords[name] = keywords
            logger.info(f"Tool registered: {name}")
            return fn
        return decorator

    def detect(self, user_input: str) -> Optional[str]:
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


# ── Tools ─────────────────────────────────────────────────────────

@tool_registry.register("time", keywords=["time", "what time", "current time", "date", "today", "day is it"])
async def get_time(_: str) -> str:
    now = datetime.now()
    return f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d %Y')}."


@tool_registry.register("weather", keywords=["weather", "temperature", "forecast", "raining", "sunny", "humidity", "wind"])
async def get_weather(_: str) -> str:
    """Live weather via Open-Meteo. Location read from settings."""
    import httpx
    from app.config import settings

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude":         settings.LOCATION_LAT,
                    "longitude":        settings.LOCATION_LON,
                    "current_weather":  True,
                    "hourly":           "relative_humidity_2m,precipitation_probability",
                    "forecast_days":    1,
                },
            )
        d  = r.json()
        cw = d["current_weather"]
        desc = _weather_code(int(cw["weathercode"]))
        temp = cw["temperature"]
        wind = cw["windspeed"]
        loc  = settings.LOCATION_NAME
        return f"{loc}: {desc}, {temp}°C, wind {wind} km/h."
    except Exception as e:
        return f"Couldn't fetch weather: {e}"


def _weather_code(code: int) -> str:
    codes = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Icy fog", 51: "Light drizzle", 53: "Drizzle",
        55: "Heavy drizzle", 61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
        80: "Rain showers", 81: "Moderate showers", 82: "Violent showers",
        95: "Thunderstorm", 96: "Thunderstorm with hail",
    }
    return codes.get(code, f"Conditions code {code}")


@tool_registry.register("open_app", keywords=[
    "open chrome", "open spotify", "open notepad", "open calculator",
    "open terminal", "open vscode", "open vs code", "open finder",
    "launch chrome", "launch spotify", "start chrome",
])
async def open_app(user_input: str) -> str:
    lower    = user_input.lower()
    os_name  = platform.system()

    windows_map = {
        "chrome":      "start chrome",
        "spotify":     "start spotify",
        "notepad":     "notepad",
        "calculator":  "calc",
        "terminal":    "start cmd",
        "vs code":     "code .",
        "vscode":      "code .",
        "explorer":    "explorer",
    }
    mac_map = {
        "chrome":      "open -a 'Google Chrome'",
        "spotify":     "open -a Spotify",
        "terminal":    "open -a Terminal",
        "vs code":     "open -a 'Visual Studio Code'",
        "vscode":      "open -a 'Visual Studio Code'",
        "finder":      "open -a Finder",
        "calculator":  "open -a Calculator",
    }

    mapping = windows_map if os_name == "Windows" else mac_map
    for key, cmd in mapping.items():
        if key in lower:
            subprocess.Popen(cmd, shell=True)
            return f"Opening {key.title()}."

    return "I couldn't identify which app to open. Try being more specific."


@tool_registry.register("rap", keywords=["rap", "spit bars", "freestyle", "rhyme for me", "give me bars"])
async def rap_for_me(user_input: str) -> str:
    lower = user_input.lower()
    for w in ["rap", "about", "on", "for", "freestyle", "me"]:
        lower = lower.replace(w, " ")
    topic = re.sub(r'\s+', ' ', lower).strip() or "life and hustle"
    return (
        f"[RAP_MODE topic='{topic}'] "
        f"Write a punchy 4-bar rap verse with rhyming couplets about '{topic}'. "
        "Be creative, rhythmic, and witty. Format: line1 / line2 / line3 / line4. No intro."
    )


@tool_registry.register("sing", keywords=["sing", "sing a song", "hum", "song for me", "sing about"])
async def sing_for_me(user_input: str) -> str:
    lower = user_input.lower()
    for w in ["sing", "a song", "about", "for me", "hum"]:
        lower = lower.replace(w, " ")
    topic = re.sub(r'\s+', ' ', lower).strip() or "sunshine and good vibes"
    return (
        f"[SING_MODE topic='{topic}'] "
        f"Write short original song lyrics (verse + chorus) about '{topic}'. "
        "Make it melodic, expressive, and fun. Label Verse and Chorus clearly."
    )


@tool_registry.register("joke", keywords=["joke", "make me laugh", "funny", "tell me something funny", "crack a joke"])
async def tell_joke(_: str) -> str:
    """Jokes are generated by the LLM, not hardcoded — always fresh."""
    # Return a prompt that the LLM will handle
    return "[JOKE_MODE] Tell a single sharp, punchy tech or life joke. One setup, one punchline. No intro."


@tool_registry.register("search", keywords=[
    "search for", "look up", "google", "find information about",
    "what is ", "who is ", "define ", "tell me about ",
])
async def web_search(user_input: str) -> str:
    """DuckDuckGo instant answer — no API key required."""
    import httpx
    query = user_input
    for w in ["search for", "look up", "google", "find information about",
              "what is", "who is", "define", "tell me about"]:
        query = query.lower().replace(w, "").strip()

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
        d = r.json()
        answer = d.get("AbstractText") or d.get("Answer") or ""
        if answer:
            return answer[:400]
        # Fall back to related topics
        topics = d.get("RelatedTopics", [])
        if topics and isinstance(topics[0], dict):
            text = topics[0].get("Text", "")
            if text:
                return text[:300]
        return f"Couldn't find a quick answer for '{query}'. I can elaborate if you'd like."
    except Exception as e:
        return f"Search failed: {e}"


@tool_registry.register("reminder", keywords=[
    "remind me", "set a reminder", "alarm", "set alarm",
    "remind", "don't let me forget", "notify me",
])
async def set_reminder(user_input: str) -> str:
    """Saves reminder to SQLite. Scheduler fires it at the right time."""
    import sqlite3
    from pathlib import Path
    from app.config import settings

    db_path = Path(settings.DATA_DIR) / "reminders.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS reminders
                    (id INTEGER PRIMARY KEY, text TEXT, created_at TEXT, triggered INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO reminders (text, created_at) VALUES (?, ?)",
                 (user_input, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return f"Reminder saved: \"{user_input.strip()}\""


@tool_registry.register("volume", keywords=["volume up", "volume down", "mute", "louder", "quieter", "set volume"])
async def control_volume(user_input: str) -> str:
    lower   = user_input.lower()
    os_name = platform.system()
    if os_name == "Darwin":
        if "up" in lower or "louder" in lower:
            subprocess.Popen("osascript -e 'set volume output volume (output volume of (get volume settings) + 10)'", shell=True)
            return "Volume increased."
        elif "down" in lower or "quieter" in lower:
            subprocess.Popen("osascript -e 'set volume output volume (output volume of (get volume settings) - 10)'", shell=True)
            return "Volume decreased."
        elif "mute" in lower:
            subprocess.Popen("osascript -e 'set volume with output muted'", shell=True)
            return "Muted."
    return "Volume control is available on macOS."


@tool_registry.register("screenshot", keywords=["screenshot", "take a screenshot", "capture screen", "screen capture"])
async def take_screenshot(_: str) -> str:
    os_name = platform.system()
    if os_name == "Darwin":
        subprocess.Popen("screencapture -x ~/Desktop/jarvis_screenshot.png", shell=True)
        return "Screenshot saved to your Desktop."
    elif os_name == "Windows":
        subprocess.Popen('powershell -command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::PrimaryScreen | Out-Null; Add-Type -AssemblyName System.Drawing; $bmp = [System.Drawing.Bitmap]::new([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen(0,0,0,0,$bmp.Size); $bmp.Save(\'$env:USERPROFILE\\Desktop\\jarvis_screenshot.png\')"', shell=True)
        return "Screenshot saved to Desktop."
    return "Screenshot not supported on this OS."


# ── import re (used in rap/sing tools) ────────────────────────────
import re


# ── Manager ───────────────────────────────────────────────────────

class ToolManager:
    async def detect_and_execute(self, user_input: str):
        name = tool_registry.detect(user_input)
        return await tool_registry.execute(name, user_input) if name else None

    async def execute(self, tool_name: str, user_input: str):
        return await tool_registry.execute(tool_name, user_input)
