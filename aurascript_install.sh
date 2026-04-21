#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# AuraScript — complete install
# Run: bash ~/Documents/JarvisAI/aurascript_install.sh
# ═══════════════════════════════════════════════════════════════════
set -e
REPO="$HOME/Documents/JarvisAI"
ROOT="$HOME/Documents/AuraScript"

echo ""
echo "  ✦ AuraScript install → $ROOT"
mkdir -p "$ROOT/src" "$ROOT/assets"

# ── package.json ──────────────────────────────────────────────────
cat > "$ROOT/package.json" << 'PKG'
{
  "name": "aurascript",
  "version": "0.1.0",
  "description": "AuraScript — The IDE that teaches, watches, and talks back.",
  "main": "src/main.js",
  "scripts": {
    "start":       "electron .",
    "dev":         "electron . --dev",
    "build:mac":   "electron-builder --mac",
    "build:win":   "electron-builder --win",
    "build:linux": "electron-builder --linux"
  },
  "author": "Archit Singhania",
  "license": "MIT",
  "devDependencies": {
    "electron":         "^31.0.0",
    "electron-builder": "^24.13.3"
  },
  "build": {
    "appId":       "com.architsinghania.aurascript",
    "productName": "AuraScript",
    "files": ["src/**/*", "assets/**/*"],
    "mac":   { "target": "dmg",      "icon": "assets/icon.icns" },
    "win":   { "target": "nsis",     "icon": "assets/icon.ico"  },
    "linux": { "target": "AppImage", "icon": "assets/icon.png"  }
  }
}
PKG

# ── src/main.js ───────────────────────────────────────────────────
cat > "$ROOT/src/main.js" << 'MAIN'
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs   = require('fs');
const { execSync } = require('child_process');
let win;

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 980, minHeight: 640,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#090c13',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'index.html'));
  if (process.argv.includes('--dev')) win.webContents.openDevTools();
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) createWindow(); });

ipcMain.handle('open-folder', async () => {
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
  return r.filePaths[0] || null;
});
ipcMain.handle('read-file',   async (_, p)    => { try { return fs.readFileSync(p, 'utf8'); } catch { return null; } });
ipcMain.handle('write-file',  async (_, p, c) => { try { fs.writeFileSync(p, c, 'utf8'); return true; } catch { return false; } });
ipcMain.handle('file-exists', async (_, p)    => fs.existsSync(p));
ipcMain.handle('list-dir',    async (_, d)    => {
  try {
    const SKIP = new Set(['.git','node_modules','__pycache__','.venv','venv','dist','build','.DS_Store']);
    return fs.readdirSync(d, { withFileTypes: true })
      .filter(e => !e.name.startsWith('.') && !SKIP.has(e.name))
      .map(e => ({ name: e.name, path: path.join(d, e.name), isDir: e.isDirectory() }))
      .sort((a, b) => (b.isDir - a.isDir) || a.name.localeCompare(b.name));
  } catch { return []; }
});
ipcMain.handle('run-command', async (_, cmd, cwd) => {
  try {
    const out = execSync(cmd, { cwd, timeout: 20000, encoding: 'utf8' });
    return { ok: true, out };
  } catch (e) { return { ok: false, out: e.stderr || e.message }; }
});
MAIN

# ── src/preload.js ────────────────────────────────────────────────
cat > "$ROOT/src/preload.js" << 'PRE'
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('aura', {
  openFolder:  ()         => ipcRenderer.invoke('open-folder'),
  readFile:    p          => ipcRenderer.invoke('read-file',   p),
  writeFile:   (p, c)     => ipcRenderer.invoke('write-file',  p, c),
  fileExists:  p          => ipcRenderer.invoke('file-exists', p),
  listDir:     p          => ipcRenderer.invoke('list-dir',    p),
  runCommand:  (cmd, cwd) => ipcRenderer.invoke('run-command', cmd, cwd),
  platform:    process.platform,
});
PRE

# ── copy IDE HTML → src/index.html ────────────────────────────────
if [ -f "$REPO/aurascript_ide.html" ]; then
  cp "$REPO/aurascript_ide.html" "$ROOT/src/index.html"
  echo "  ✓ IDE HTML installed"
else
  echo "  ✗ aurascript_ide.html not found in $REPO"
  exit 1
fi

# ── placeholder icon ──────────────────────────────────────────────
python3 -c "
import struct, zlib
def png(r,g,b):
    raw=bytes([0,r,g,b,255])
    cd=zlib.compress(raw)
    def ck(t,d):
        c=struct.pack('>I',len(d))+t+d
        return c+struct.pack('>I',zlib.crc32(c[4:])&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'
        +ck(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))
        +ck(b'IDAT',cd)+ck(b'IEND',b''))
open('$ROOT/assets/icon.png','wb').write(png(0,212,255))
" 2>/dev/null || echo "  ℹ  Replace assets/icon.png with a real icon later"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       AuraScript installed successfully!             ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  cd ~/Documents/AuraScript                          ║"
echo "║  npm install                                         ║"
echo "║  npm start          # or: npm run dev                ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Daisy AI must be running first:                     ║"
echo "║  cd ~/Documents/JarvisAI/backend                    ║"
echo "║  source .venv/bin/activate                           ║"
echo "║  uvicorn app.main:app --reload                       ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Keyboard shortcuts:                                 ║"
echo "║  ⌘O → Open folder    ⌘R → Run file                  ║"
echo "║  ⌘S → Save           ⌘K → Command palette           ║"
echo "║  ⌘⇧S → Checkpoint    ⌘M → Toggle voice              ║"
echo "╚══════════════════════════════════════════════════════╝"
