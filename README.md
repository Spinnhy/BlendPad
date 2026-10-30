# BlendPad Direct 📱✨

[![Blender 4.0+ & 5.x](https://img.shields.io/badge/Blender-4.0%20%7C%204.2%20LTS%20%7C%205.x-F5792A?logo=blender&logoColor=white)](https://www.blender.org/)
[![Android 8.0+](https://img.shields.io/badge/Android-8.0%2B-3DDC84?logo=android&logoColor=white)](https://play.google.com/store/apps/details?id=com.spinnhy.blendpad)
[![UDP 120Hz](https://img.shields.io/badge/Streaming-UDP%20120Hz-00F2FE)](#architecture)
[![Languages](https://img.shields.io/badge/Languages-8%20Supported-9D4EDD)](#localization)
[![License: GPL v3](https://img.shields.io/badge/Add--on%20License-GPLv3-blue.svg)](LICENSE)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-Buy%20a%20Pizza-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/ctrlside)

> **Turn your smartphone or tablet into an ultra-low latency SpaceMouse, 3D rotary dial controller, and contextual workflow deck for Blender.**

BlendPad eliminates the need for expensive dedicated 3D hardware ($150–$400) by leveraging your mobile device's high-refresh multi-touch screen. With **direct 120Hz UDP coordinate streaming**, latency is imperceptible (~1.2 ms on local Wi-Fi), providing smooth and intuitive 3D viewport navigation.

🌐 **Live Interactive Demo & Download Hub:** **[https://spinnhy.github.io/BlendPad/](https://spinnhy.github.io/BlendPad/)**

---

## 🌟 Key Features (App v1.1.0 · Add-on v1.5.0)

### 🕹️ Multi-Touch Viewport Navigation
- **1-Finger Drag**: Smooth Orbit around selected geometry or 3D cursor.
- **2-Finger Drag**: Pan along the viewport camera plane.
- **Pinch-to-Zoom**: Continuous, fine-grained focal scaling.
- **1-Finger Double-Tap Focus**: Instant `Frame Selected` (`Numpad .`) right from the touchpad.
- **Procreate-Style Multi-Touch Gestures (PRO 👑)**: **3-Finger Tap** for Undo and **4-Finger Tap** for Redo without lifting your hand from the screen.
- **Custom Sensitivity & Axis Inversion**: Independently calibrate Orbit, Pan, and Zoom speed and invert X/Y axes directly from the app.
- **Numpad View Matrix**: Instant 1-tap switching to Front (1), Right (3), Top (7), Back, Left, Bottom, Camera (0), and Perspective/Ortho (5).

### ⚡ 120Hz UDP Direct Streaming & Smart Session
- Zero cloud relay: All communication stays 100% inside your local Wi-Fi network.
- Delta coordinates are packed into compact binary UDP datagrams processed at high frequency on the Blender event loop.
- **Auto-Reconnect & Screen WakeLock**: Automatically reconnects to your last paired PC on startup and keeps your phone display awake while connected.

### 🎛️ Mode-Aware Dynamic Decks & Custom Workflow Engine
BlendPad listens to Blender's active mode in real time and shifts its on-screen controls automatically:
- **Object Mode**: Transform Gizmos (G/R/S), Duplicate, Local View Isolate, Shade Smooth/Flat, Origin to Geometry, Apply All Transforms.
- **Edit Mesh Mode**: Vertex / Edge / Face selection filters, Extrude (E), Inset (I), Bevel (Ctrl+B), Loop Cut (Ctrl+R), Knife (K), Merge by Distance (M), Fill (F), Delete (X).
- **Sculpt Mode**: Direct Brush Deck (Draw, Clay Strips, Grab, Smooth, Inflate, Crease, Flatten, Mask), 3D Haptic Rotary Dials for Brush Radius & Strength, Dyntopo, Voxel Remesh, Clear Mask, X-Symmetry.
- **Custom Workflow Manager (PRO 👑)**: Create unlimited custom workflows, rename or reorder tabs, assign automatic Blender mode triggers, and mirror the entire layout in 1 tap for left-handed or right-handed desk setups.

### 📱 Zero-Config QR Quick Pairing
No typing local IP addresses or configuring router NATs:
1. Press `N` in Blender's 3D Viewport to reveal the **BlendPad** panel.
2. Click **Avvia Server**.
3. Scan the on-screen QR Code with the BlendPad mobile app. Paired in 2 seconds with automatic local token authentication!

### 🌍 8 Native Languages
BlendPad detects your system language automatically and supports:
- 🇺🇸 English
- 🇮🇹 Italiano
- 🇪🇸 Español
- 🇫🇷 Français
- 🇩🇪 Deutsch
- 🇵🇹 Português
- 🇯🇵 日本語
- 🇨🇳 简体中文

---

## 🚀 Quick Start Guide

### Step 1: Install Blender Add-on (`v1.5.0`)
1. Download [`blendpad_blender.zip`](https://spinnhy.github.io/BlendPad/releases/blendpad_blender.zip).
2. Open Blender (**4.0, 4.1, 4.2 LTS, or 5.x**).
3. Go to **Edit > Preferences > Add-ons**.
4. Click **Install from Disk** (top-right) and select `blendpad_blender.zip`.
5. Check the box to enable **BlendPad Direct**.

### Step 2: Start the Daemon
1. In the 3D Viewport, press **`N`** to open the right sidebar.
2. Select the **BlendPad** tab.
3. Click **Avvia Server**. A QR code overlay will appear in the viewport.

### Step 3: Launch BlendPad Mobile
1. Install and open the BlendPad app on your Android device ([Google Play Store](https://play.google.com/store/apps/details?id=com.spinnhy.blendpad)).
2. Tap **Scan QR** and point your camera at the QR code in Blender.
3. You're connected! Use your phone screen to orbit, pan, zoom, and trigger shortcuts.

---

## 📊 Free vs Studio PRO

| Capability | Free Tier | Studio PRO 👑 |
|---|:---:|:---:|
| 120Hz UDP Touchpad (1-Finger Orbit, 2-Finger Pan, Pinch Zoom) | ✅ | ✅ |
| Custom Orbit / Pan / Zoom Sensitivity & Axis Inversion | ✅ | ✅ |
| 1-Finger Double-Tap Focus (`Frame Selected`) & Numpad View Matrix | ✅ | ✅ |
| QR Pairing, Auto-Reconnect & Automatic Screen WakeLock | ✅ | ✅ |
| Standard Mode Workflows (Object, Edit Mesh, Sculpt) & Basic Layout Move/Resize | ✅ (3 Decks) | ✅ (Unlimited) |
| Custom Workflow Manager (Create, Rename, Reorder & Auto-Sync Mode Triggers) | — | ✅ |
| 3D Haptic Rotary Dials (Brush Radius, Strength & Timeline Scrubber) | — | ✅ |
| Procreate-Style Multi-Touch Gestures (3-Finger Undo / 4-Finger Redo) | — | ✅ |
| Advanced Sculpt, Topology & Object Decks (Brushes, Remesh, Loop Cut, Knife, Shading) | — | ✅ |
| 1-Tap Left/Right-Handed Horizontal Flip & JSON Layout Backup | — | ✅ |
| Custom Python Operators (`bpy.ops.*`) & Blender Macros | — | ✅ |

---

## 🛠️ Network & Troubleshooting

BlendPad communicates entirely within your local local area network (LAN/Wi-Fi):
- **UDP Port**: `4242` (High-frequency touch streaming)
- **TCP Port**: `4243` (Commands, state sync, security handshake)

### Common Checks:
- **Same Wi-Fi Network**: Ensure both your PC and phone are connected to the same Wi-Fi router (avoid guest networks with client isolation).
- **Windows / OS Firewall**: When Blender requests network access, allow private networks. If connection fails, allow UDP 4242 and TCP 4243 in your firewall settings.
- **Port Customization**: You can change the listening ports at any time in Blender: Sidebar `N` > BlendPad > Porte.

---

## 🏗️ Architecture

```
┌─────────────────────────────────┐           ┌──────────────────────────────────┐
│         Android Device          │           │          Blender Host            │
│       (BlendPad Flutter)        │           │        (BlendPad Add-on)         │
│                                 │           │                                  │
│  [ Touchpad / Gestures ] ───────┼── UDP ────┼──> [ 120Hz Coordinate Processor ] │
│  (1-Finger, 2-Finger, Pinch)    │  (4242)   │    (Viewport Camera Orbit/Pan)   │
│                                 │           │                                  │
│  [ Mode & Action Buttons ] ─────┼── TCP ────┼──> [ Command Executor ]          │
│  (Vistas, Sculpt, Edit, Dials)  │  (4243)   │    (bpy.ops.*, Tool switching)   │
│                                 │           │                                  │
│  [ QR Code Scanner ] <──────────┼── Visual ─┼─── [ Viewport QR Overlay ]       │
└─────────────────────────────────┘           └──────────────────────────────────┘
```

---

## 🍕 Support CtrlSide

BlendPad is an open-source initiative developed by **CtrlSide**. Our goal is to empower 3D artists and makers by transforming screens they already own into ergonomic, low-latency companion controllers.

If BlendPad speeds up your workflow and saves you money, consider supporting development by **[buying a slice of pizza on Ko-fi](https://ko-fi.com/ctrlside)**! 🍕

<p align="center">
  <a href="https://ko-fi.com/ctrlside" target="_blank">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi" height="38">
  </a>
</p>

---

## 📄 License

- **Blender Add-on (`blender_addon/`)**: Free and Open-Source Software licensed under the **GNU General Public License v2.0 or later (GPL-2.0-or-later / GPL-3.0)** in compliance with the Blender Python API (`bpy`). See the [LICENSE](LICENSE) file for details.
- **BlendPad Mobile App (Android)**: Proprietary software copyright © CtrlSide (Spinnhy), distributed via [Google Play Store](https://play.google.com/store/apps/details?id=com.spinnhy.blendpad).

Blender is a registered trademark of the Blender Foundation.
