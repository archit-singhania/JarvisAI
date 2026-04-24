#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# AuraScript — complete install / reinstall
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
  "version": "1.0.0",
  "description": "AuraScript — The IDE that watches, teaches, and talks back.",
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
    "mac": {
      "target": "dmg",
      "icon":   "assets/icon.icns",
      "category": "public.app-category.developer-tools"
    },
    "win": {
      "target": "nsis",
      "icon":   "assets/icon.ico"
    },
    "linux": {
      "target": "AppImage",
      "icon":   "assets/icon.png"
    }
  }
}
PKG

# ── src/main.js ───────────────────────────────────────────────────
cat > "$ROOT/src/main.js" << 'MAIN'
const { app, BrowserWindow, ipcMain, dialog, Menu, shell } = require('electron');
const path = require('path');
const fs   = require('fs');
const { execSync, exec } = require('child_process');
let win;
const isDev = process.argv.includes('--dev');

function createWindow() {
  win = new BrowserWindow({
    width:     1480,
    height:    920,
    minWidth:  1000,
    minHeight: 660,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: { x: 16, y: 11 },
    backgroundColor: '#02030a',
    vibrancy: process.platform === 'darwin' ? 'under-window' : undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });

  win.loadFile(path.join(__dirname, 'index.html'));
  if (isDev) win.webContents.openDevTools({ mode: 'detach' });

  // Native menu
  const template = [
    {
      label: 'AuraScript',
      submenu: [
        { label: 'About AuraScript', role: 'about' },
        { type: 'separator' },
        { label: 'Quit', accelerator: 'CmdOrCtrl+Q', click: () => app.quit() },
      ]
    },
    {
      label: 'File',
      submenu: [
        { label: 'Open Folder…', accelerator: 'CmdOrCtrl+O',
          click: () => win.webContents.executeJavaScript('openFolder()') },
        { label: 'Save',  accelerator: 'CmdOrCtrl+S',
          click: () => win.webContents.executeJavaScript('saveFile()') },
        { label: 'New File', accelerator: 'CmdOrCtrl+N',
          click: () => win.webContents.executeJavaScript('newFile()') },
      ]
    },
    {
      label: 'Run',
      submenu: [
        { label: 'Run File', accelerator: 'CmdOrCtrl+R',
          click: () => win.webContents.executeJavaScript('runFile()') },
        { label: 'Save Checkpoint', accelerator: 'CmdOrCtrl+Shift+S',
          click: () => win.webContents.executeJavaScript('gitCheckpoint()') },
      ]
    },
    {
      label: 'View',
      submenu: [
        { label: 'Command Palette', accelerator: 'CmdOrCtrl+K',
          click: () => win.webContents.executeJavaScript('openPalette()') },
        { label: 'Toggle Focus Mode', accelerator: 'CmdOrCtrl+Shift+F',
          click: () => win.webContents.executeJavaScript('toggleFocus()') },
        { label: 'Toggle Terminal', accelerator: 'CmdOrCtrl+`',
          click: () => win.webContents.executeJavaScript('togglePanel()') },
        { type: 'separator' },
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ]
    },
    {
      label: 'Wednesday',
      submenu: [
        { label: 'Ask Wednesday: Review Code',
          click: () => win.webContents.executeJavaScript("askWed('Review this code')") },
        { label: 'Ask Wednesday: Explain File',
          click: () => win.webContents.executeJavaScript("askWed('Explain what this code does')") },
        { label: 'Ask Wednesday: Debug',
          click: () => win.webContents.executeJavaScript("askWed('Debug any issues in this code')") },
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' },
        { role: 'selectAll' },
      ]
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) createWindow(); });

// ── IPC handlers ─────────────────────────────────────────────────
ipcMain.handle('open-folder', async () => {
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
  return r.filePaths[0] || null;
});

ipcMain.handle('read-file', async (_, p) => {
  try { return fs.readFileSync(p, 'utf8'); } catch { return null; }
});

ipcMain.handle('write-file', async (_, p, c) => {
  try { fs.writeFileSync(p, c, 'utf8'); return true; } catch { return false; }
});

ipcMain.handle('file-exists', async (_, p) => fs.existsSync(p));

ipcMain.handle('list-dir', async (_, d) => {
  const SKIP = new Set(['.git','node_modules','__pycache__','.venv','venv',
                         'dist','build','.idea','.DS_Store','coverage']);
  try {
    return fs.readdirSync(d, { withFileTypes: true })
      .filter(e => !e.name.startsWith('.') && !SKIP.has(e.name))
      .map(e => ({ name: e.name, path: path.join(d, e.name), isDir: e.isDirectory() }))
      .sort((a, b) => (b.isDir - a.isDir) || a.name.localeCompare(b.name));
  } catch { return []; }
});

ipcMain.handle('run-command', async (_, cmd, cwd) => {
  try {
    const out = execSync(cmd, { cwd, timeout: 30000, encoding: 'utf8', maxBuffer: 1024 * 512 });
    return { ok: true, out };
  } catch (e) {
    return { ok: false, out: (e.stderr || e.stdout || e.message || '').slice(0, 2000) };
  }
});

ipcMain.handle('platform', () => process.platform);
MAIN

# ── src/preload.js ────────────────────────────────────────────────
cat > "$ROOT/src/preload.js" << 'PRE'
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('aura', {
  openFolder:  ()         => ipcRenderer.invoke('open-folder'),
  readFile:    p          => ipcRenderer.invoke('read-file',    p),
  writeFile:   (p, c)     => ipcRenderer.invoke('write-file',   p, c),
  fileExists:  p          => ipcRenderer.invoke('file-exists',  p),
  listDir:     p          => ipcRenderer.invoke('list-dir',     p),
  runCommand:  (cmd, cwd) => ipcRenderer.invoke('run-command',  cmd, cwd),
  platform:    () =>         ipcRenderer.invoke('platform'),
});
PRE

# ── copy IDE HTML ─────────────────────────────────────────────────
if [ -f "$REPO/aurascript_ide.html" ]; then
  cp "$REPO/aurascript_ide.html" "$ROOT/src/index.html"
  echo "  ✓ IDE HTML installed"
else
  echo "  ✗ aurascript_ide.html not found in $REPO"
  exit 1
fi

# ── placeholder icon ──────────────────────────────────────────────
python3 -c "
import struct, zlib, os
def make_png(r,g,b,a=255):
    idat=zlib.compress(bytes([0,r,g,b,a]))
    def chunk(t,d):
        c=struct.pack('>I',len(d))+t+d
        return c+struct.pack('>I',zlib.crc32(c[4:])&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'
        +chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))
        +chunk(b'IDAT',idat)+chunk(b'IEND',b''))
os.makedirs('$ROOT/assets',exist_ok=True)
open('$ROOT/assets/icon.png','wb').write(make_png(124,108,252))
" 2>/dev/null || echo "  ℹ  Replace assets/icon.png with your real icon later"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         AuraScript installed successfully!               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  1. cd ~/Documents/AuraScript                           ║"
echo "║  2. npm install                                          ║"
echo "║  3. npm start          (or: npm run dev for DevTools)    ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Wednesday AI backend must be running first:             ║"
echo "║  cd ~/Documents/JarvisAI/backend                        ║"
echo "║  source .venv/bin/activate                               ║"
echo "║  uvicorn app.main:app --reload                           ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Keyboard shortcuts:                                     ║"
echo "║  ⌘O  Open folder     ⌘R  Run file                       ║"
echo "║  ⌘S  Save file       ⌘K  Command palette                ║"
echo "║  ⌘⇧S Checkpoint      ⌘⇧F Focus mode                     ║"
echo "║  ⌘`  Toggle terminal                                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
