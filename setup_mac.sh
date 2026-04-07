#!/bin/bash
# setup_mac.sh — run this once from the project root on macOS
# It creates missing directories, the test UI, and installs Python deps.
# Usage:  bash setup_mac.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "==> JarvisAI macOS setup from: $ROOT"

# 1. Create missing directories
mkdir -p "$ROOT/ui"
mkdir -p "$ROOT/data/vectordb"
mkdir -p "$ROOT/models/piper"
mkdir -p "$ROOT/logs"
echo "✅ Directories created"

# 2. Write the web test UI
cat > "$ROOT/ui/index.html" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Jarvis AI — Test UI</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg-deep:#0a0e1a; --bg-panel:#111827; --bg-card:#1c2333;
    --cyan:#00d4ff; --blue:#3b82f6; --green:#10b981;
    --amber:#f59e0b; --red:#ef4444; --text:#f0f4ff; --muted:#8b9dc3; --border:#1c2a44;
  }
  body { background:var(--bg-deep); color:var(--text);
         font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",sans-serif;
         height:100vh; display:flex; flex-direction:column; overflow:hidden; }
  header { display:flex; align-items:center; gap:12px; padding:12px 20px;
           background:var(--bg-panel); border-bottom:1px solid var(--border); flex-shrink:0; }
  .logo-dot { width:10px; height:10px; border-radius:50%; background:var(--cyan); }
  .logo-text { font-size:13px; font-weight:600; letter-spacing:3px; color:var(--cyan); }
  #conn-badge { margin-left:auto; font-size:11px; padding:3px 10px; border-radius:20px;
                border:1px solid var(--border); color:var(--muted); }
  #conn-badge.connected { color:var(--green); border-color:var(--green); }
  #conn-badge.error     { color:var(--red);   border-color:var(--red);   }
  .layout { display:flex; flex:1; overflow:hidden; }
  aside { width:196px; background:var(--bg-panel); border-right:1px solid var(--border);
          padding:14px 10px; display:flex; flex-direction:column; gap:6px; flex-shrink:0; overflow-y:auto; }
  .section-label { font-size:10px; letter-spacing:2px; color:var(--muted);
                   text-transform:uppercase; padding:4px 0 2px; }
  .sidebar-btn { background:var(--bg-card); border:1px solid var(--border); color:var(--cyan);
                 padding:7px 10px; border-radius:7px; font-size:12px; cursor:pointer;
                 text-align:left; transition:background .15s; }
  .sidebar-btn:hover { background:#00d4ff18; }
  .chat-area { flex:1; display:flex; flex-direction:column; overflow:hidden; }
  #waveform { display:none; align-items:center; justify-content:center; gap:2px;
              height:44px; background:var(--bg-panel); border-bottom:1px solid var(--border); padding:0 16px; }
  #waveform.active { display:flex; }
  .bar { width:3px; background:var(--cyan); border-radius:2px; transition:height .05s; min-height:4px; }
  #messages { flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:8px; }
  #messages::-webkit-scrollbar { width:4px; }
  #messages::-webkit-scrollbar-thumb { background:var(--border); border-radius:2px; }
  .bubble { max-width:72%; padding:10px 14px; border-radius:12px; font-size:14px;
            line-height:1.6; animation:fadeIn .2s ease; }
  @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1} }
  .bubble.user   { align-self:flex-end;   background:#1c3a6e; border-bottom-right-radius:3px; }
  .bubble.jarvis { align-self:flex-start; background:#0e2a38; border-bottom-left-radius:3px; border-left:2px solid var(--cyan); }
  .bubble.system { align-self:center; background:transparent; border:1px solid var(--border);
                   color:var(--muted); font-size:11px; padding:4px 12px; border-radius:20px; }
  .bubble.reminder { align-self:center; background:#2a1800; border:1px solid var(--amber); color:var(--amber); font-size:12px; }
  .bubble .sender { font-size:10px; color:var(--muted); margin-bottom:4px;
                    letter-spacing:1px; text-transform:uppercase; }
  .bubble.jarvis .sender { color:var(--cyan); }
  .cursor::after { content:"▋"; color:var(--cyan); animation:blink .7s step-end infinite; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  .input-bar { display:flex; align-items:center; gap:8px; padding:12px 14px;
               background:var(--bg-panel); border-top:1px solid var(--border); flex-shrink:0; }
  #text-input { flex:1; background:var(--bg-card); border:1px solid var(--border); color:var(--text);
                padding:10px 14px; border-radius:10px; font-size:14px; outline:none; transition:border-color .15s; }
  #text-input:focus { border-color:var(--cyan); }
  #text-input::placeholder { color:var(--muted); }
  .btn { background:var(--bg-card); border:1px solid var(--border); color:var(--cyan);
         padding:10px 16px; border-radius:10px; font-size:13px; cursor:pointer;
         transition:background .15s; white-space:nowrap; }
  .btn:hover { background:#00d4ff18; }
  .btn.danger { color:var(--red); border-color:var(--red); }
  .btn.danger:hover { background:#ef444418; }
  #mic-btn { font-size:18px; padding:10px 13px; }
  #mic-btn.active { background:var(--cyan); color:var(--bg-deep); border-color:var(--cyan); }
  .tools-panel { width:200px; background:var(--bg-panel); border-left:1px solid var(--border);
                 padding:14px 10px; overflow-y:auto; flex-shrink:0; }
  .tool-entry { background:var(--bg-card); border:1px solid var(--border); border-radius:7px;
                padding:7px 9px; font-size:11px; color:var(--cyan); margin-bottom:5px;
                word-break:break-word; animation:fadeIn .2s ease; }
  .tool-entry .tool-name { color:var(--amber); font-weight:600; margin-bottom:2px; }
</style>
</head>
<body>
<header>
  <div class="logo-dot"></div>
  <span class="logo-text">JARVIS AI</span>
  <span style="font-size:11px;color:var(--muted)">macOS Test UI</span>
  <div id="conn-badge">● Connecting...</div>
</header>
<div class="layout">
  <aside>
    <div class="section-label">Quick tests</div>
    <button class="sidebar-btn" onclick="sendQuick('What time is it?')">🕐 Time</button>
    <button class="sidebar-btn" onclick="sendQuick('What is the weather?')">🌤 Weather</button>
    <button class="sidebar-btn" onclick="sendQuick('Tell me a joke')">😄 Joke</button>
    <button class="sidebar-btn" onclick="sendQuick('Rap for me about coding')">🎤 Rap</button>
    <button class="sidebar-btn" onclick="sendQuick('Sing a song about the moon')">🎵 Sing</button>
    <button class="sidebar-btn" onclick="sendQuick('Search for latest AI news')">🔍 Search</button>
    <button class="sidebar-btn" onclick="sendQuick('Open calculator')">💻 Open app</button>
    <button class="sidebar-btn" onclick="sendQuick('Remind me in 1 minute to stretch')">⏰ Reminder</button>
    <div class="section-label" style="margin-top:6px">Actions</div>
    <button class="sidebar-btn" onclick="sendInterrupt()">⛔ Interrupt</button>
    <button class="sidebar-btn" onclick="sendClear()">🗑 Clear chat</button>
    <div class="section-label" style="margin-top:6px">Memory</div>
    <button class="sidebar-btn" onclick="addMemory()">📥 Add fact</button>
  </aside>
  <div class="chat-area">
    <div id="waveform"></div>
    <div id="messages"></div>
    <div class="input-bar">
      <input id="text-input" placeholder="Ask Jarvis anything… (Enter to send)"
             onkeydown="if(event.key==='Enter')sendText()"/>
      <button class="btn" id="mic-btn" onclick="toggleMic()" title="Click to record">🎤</button>
      <button class="btn" onclick="sendText()">Send</button>
      <button class="btn danger" onclick="sendInterrupt()">⛔</button>
    </div>
  </div>
  <div class="tools-panel">
    <div class="section-label">Tool activity</div>
    <div id="tool-log"></div>
  </div>
</div>
<script>
let ws=null,streamBubble=null,streamContent='',mediaRecorder=null,audioChunks=[],isRecording=false,waveInterval=null;
const BARS=36;
function connect(){
  ws=new WebSocket('ws://localhost:8000/ws');
  ws.onopen=()=>{setBadge('● Connected','connected');addSystem('Connected to Jarvis backend ✓');};
  ws.onclose=()=>{setBadge('● Disconnected','error');addSystem('Reconnecting...');setTimeout(connect,3000);};
  ws.onerror=()=>setBadge('● Error','error');
  ws.onmessage=e=>handle(JSON.parse(e.data));
}
function handle(d){
  if(d.type==='stream_start'){streamContent='';streamBubble=addBubble('jarvis','',true);}
  else if(d.type==='stream_chunk'){streamContent+=d.content;if(streamBubble)streamBubble.querySelector('.body').textContent=streamContent;scrollBottom();}
  else if(d.type==='stream_end'){if(streamBubble){streamBubble.querySelector('.body').textContent=d.content||streamContent;streamBubble.classList.remove('cursor');streamBubble=null;}if(d.tool_used)logTool(d.tool_used,d.content);scrollBottom();}
  else if(d.type==='stream_interrupted'){if(streamBubble){streamBubble.querySelector('.body').textContent+=' [stopped]';streamBubble.classList.remove('cursor');streamBubble=null;}addSystem('Interrupted');}
  else if(d.type==='text'){addBubble('jarvis',d.content);if(d.tool_used)logTool(d.tool_used,d.content);}
  else if(d.type==='audio'){addBubble('jarvis',d.content);if(d.tool_used)logTool(d.tool_used,d.content);if(d.audio_b64)playB64(d.audio_b64,d.audio_format);}
  else if(d.type==='reminder'){addReminder(d.content);}
  else if(d.type==='wake_detected'){addSystem('🎙 '+d.content);}
  else if(d.type==='interrupted'){addSystem('⛔ Interrupted');}
  else if(d.type==='cleared'){document.getElementById('messages').innerHTML='';document.getElementById('tool-log').innerHTML='';addSystem('Chat cleared');}
}
function sendText(){const inp=document.getElementById('text-input');const t=inp.value.trim();if(!t||!ws||ws.readyState!==1)return;addBubble('user',t);ws.send(JSON.stringify({type:'text',content:t}));inp.value='';}
function sendQuick(t){document.getElementById('text-input').value=t;sendText();}
function sendInterrupt(){if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'interrupt'}));}
function sendClear(){if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'clear'}));}
function addMemory(){const f=prompt('Enter a fact for Jarvis to remember:');if(!f)return;fetch('/api/rag/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:f,doc_id:'fact_'+Date.now()})}).then(()=>addSystem('Memory saved: '+f));}
async function toggleMic(){isRecording?stopRec():await startRec();}
async function startRec(){try{const s=await navigator.mediaDevices.getUserMedia({audio:true});audioChunks=[];mediaRecorder=new MediaRecorder(s);mediaRecorder.ondataavailable=e=>audioChunks.push(e.data);mediaRecorder.onstop=async()=>{const blob=new Blob(audioChunks,{type:'audio/webm'});const ab=await blob.arrayBuffer();const b64=btoa(String.fromCharCode(...new Uint8Array(ab)));ws.send(JSON.stringify({type:'audio',audio_b64:b64}));s.getTracks().forEach(t=>t.stop());};mediaRecorder.start();isRecording=true;document.getElementById('mic-btn').classList.add('active');startWave();addSystem('Recording… click 🎤 to stop');}catch{addSystem('Mic denied — use text mode');}}
function stopRec(){if(mediaRecorder&&isRecording){mediaRecorder.stop();isRecording=false;document.getElementById('mic-btn').classList.remove('active');stopWave();addBubble('user','🎤 [Voice message sent]');}}
function startWave(){const wf=document.getElementById('waveform');wf.innerHTML='';for(let i=0;i<BARS;i++){const b=document.createElement('div');b.className='bar';wf.appendChild(b);}wf.classList.add('active');waveInterval=setInterval(()=>wf.querySelectorAll('.bar').forEach(b=>b.style.height=(4+Math.random()*34)+'px'),60);}
function stopWave(){clearInterval(waveInterval);document.getElementById('waveform').classList.remove('active');}
function playB64(b64,fmt){const mime=fmt==='mp3'?'audio/mpeg':'audio/wav';const bytes=atob(b64);const arr=new Uint8Array(bytes.length);for(let i=0;i<bytes.length;i++)arr[i]=bytes.charCodeAt(i);const url=URL.createObjectURL(new Blob([arr],{type:mime}));new Audio(url).play().catch(()=>{});}
function addBubble(role,content,streaming=false){const m=document.getElementById('messages');const d=document.createElement('div');d.className='bubble '+role+(streaming?' cursor':'');const s=document.createElement('div');s.className='sender';s.textContent=role==='user'?'You':'Jarvis';const b=document.createElement('div');b.className='body';b.textContent=content;d.appendChild(s);d.appendChild(b);m.appendChild(d);scrollBottom();return d;}
function addSystem(t){const m=document.getElementById('messages');const d=document.createElement('div');d.className='bubble system';d.textContent=t;m.appendChild(d);scrollBottom();}
function addReminder(t){const m=document.getElementById('messages');const d=document.createElement('div');d.className='bubble reminder';d.innerHTML='<div class="sender">⏰ Reminder</div><div>'+t+'</div>';m.appendChild(d);scrollBottom();if(Notification.permission==='granted')new Notification('Jarvis',{body:t});}
function logTool(name,content){const log=document.getElementById('tool-log');const d=document.createElement('div');d.className='tool-entry';const p=(content||'').substring(0,70)+(content&&content.length>70?'…':'');d.innerHTML='<div class="tool-name">'+name+'</div>'+p;log.insertBefore(d,log.firstChild);if(log.children.length>8)log.removeChild(log.lastChild);}
function setBadge(t,c){const b=document.getElementById('conn-badge');b.textContent=t;b.className=c;}
function scrollBottom(){const m=document.getElementById('messages');m.scrollTop=m.scrollHeight;}
if('Notification' in window&&Notification.permission==='default')Notification.requestPermission();
connect();
</script>
</body>
</html>
HTMLEOF

echo "✅ Web test UI written to ui/index.html"

# 3. Python venv + install
cd "$ROOT/backend"
if [ ! -d ".venv" ]; then
  echo "==> Creating Python venv..."
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "==> Installing Python dependencies (this may take a few minutes)..."
pip install --upgrade pip -q

# Install core deps that work on macOS (skip TTS / pyaudio initially)
pip install fastapi uvicorn[standard] websockets pydantic pydantic-settings \
            python-dotenv groq httpx aiohttp requests beautifulsoup4 \
            chromadb sentence-transformers loguru python-dateutil -q

echo ""
echo "✅ Core deps installed"
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  To run Jarvis AI on macOS:"
echo ""
echo "  1. Add your Groq key to backend/.env:"
echo "     GROQ_API_KEY=your-key-here"
echo ""
echo "  2. Start the server:"
echo "     cd backend && source .venv/bin/activate"
echo "     uvicorn app.main:app --reload"
echo ""
echo "  3. Open the test UI in your browser:"
echo "     http://localhost:8000/ui"
echo ""
echo "  WPF desktop (Windows only) — use the web UI on Mac."
echo "═══════════════════════════════════════════════════════"
