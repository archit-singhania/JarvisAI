#!/bin/bash
# =============================================================
# AuraScript — scaffold script
# Run once from ~/Documents:   bash /path/to/JarvisAI/aurascript_setup.sh
# Creates ~/Documents/AuraScript with full project structure
# =============================================================
set -e
ROOT="$HOME/Documents/AuraScript"
echo "Creating AuraScript at $ROOT"
mkdir -p "$ROOT/src/components" "$ROOT/src/services" "$ROOT/src/utils" "$ROOT/assets"

# ── package.json ──────────────────────────────────────────────
cat > "$ROOT/package.json" << 'EOF'
{
  "name": "aurascript",
  "version": "0.1.0",
  "description": "AuraScript — The IDE that teaches, watches, and talks back.",
  "main": "src/main.js",
  "scripts": {
    "start": "electron .",
    "dev": "electron . --dev",
    "build:mac": "electron-builder --mac",
    "build:win": "electron-builder --win",
    "build:linux": "electron-builder --linux"
  },
  "author": "Archit Singhania",
  "license": "MIT",
  "devDependencies": {
    "electron": "^31.0.0",
    "electron-builder": "^24.13.3"
  },
  "dependencies": {
    "isomorphic-git": "^1.27.0"
  },
  "build": {
    "appId": "com.architsinghania.aurascript",
    "productName": "AuraScript",
    "files": ["src/**/*", "assets/**/*", "node_modules/**/*"],
    "mac": { "target": "dmg", "icon": "assets/icon.icns" },
    "win": { "target": "nsis", "icon": "assets/icon.ico" },
    "linux": { "target": "AppImage", "icon": "assets/icon.png" }
  }
}
EOF

# ── main.js (Electron main process) ───────────────────────────
cat > "$ROOT/src/main.js" << 'MAINEOF'
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const fs = require('fs');

let win;

function createWindow() {
  win = new BrowserWindow({
    width: 1400, height: 900,
    minWidth: 900, minHeight: 600,
    titleBarStyle: 'hiddenInset',   // macOS native traffic lights
    backgroundColor: '#0a0d14',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
  });

  win.loadFile(path.join(__dirname, 'index.html'));

  // Dev tools in development
  if (process.argv.includes('--dev')) {
    win.webContents.openDevTools();
  }
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

// ── IPC: open folder dialog ────────────────────────────────────
ipcMain.handle('open-folder', async () => {
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory'],
    title: 'Open Project Folder',
  });
  return result.filePaths[0] || null;
});

// ── IPC: read file ─────────────────────────────────────────────
ipcMain.handle('read-file', async (_, filePath) => {
  try { return fs.readFileSync(filePath, 'utf8'); }
  catch(e) { return null; }
});

// ── IPC: write file ────────────────────────────────────────────
ipcMain.handle('write-file', async (_, filePath, content) => {
  try { fs.writeFileSync(filePath, content, 'utf8'); return true; }
  catch(e) { return false; }
});

// ── IPC: list directory ────────────────────────────────────────
ipcMain.handle('list-dir', async (_, dirPath) => {
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    return entries.map(e => ({
      name: e.name,
      path: path.join(dirPath, e.name),
      isDir: e.isDirectory(),
    })).filter(e => !e.name.startsWith('.') &&
                    !['node_modules', '__pycache__', '.git', 'dist', 'build'].includes(e.name));
  } catch(e) { return []; }
});

// ── IPC: run terminal command ──────────────────────────────────
ipcMain.handle('run-command', async (_, cmd, cwd) => {
  const { execSync } = require('child_process');
  try {
    const out = execSync(cmd, { cwd, timeout: 15000, encoding: 'utf8' });
    return { success: true, output: out };
  } catch(e) {
    return { success: false, output: e.message };
  }
});
MAINEOF

# ── preload.js ─────────────────────────────────────────────────
cat > "$ROOT/src/preload.js" << 'PREEOF'
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aura', {
  openFolder:   ()             => ipcRenderer.invoke('open-folder'),
  readFile:     (p)            => ipcRenderer.invoke('read-file', p),
  writeFile:    (p, c)         => ipcRenderer.invoke('write-file', p, c),
  listDir:      (p)            => ipcRenderer.invoke('list-dir', p),
  runCommand:   (cmd, cwd)     => ipcRenderer.invoke('run-command', cmd, cwd),
});
PREEOF

echo "✅ Electron shell created"
echo ""
echo "Next steps:"
echo "  cd $ROOT"
echo "  npm install"
echo "  npm start"
echo ""
echo "Then open http://localhost:8000 for Daisy AI backend"
