# BlendPad Direct 📱✨

[![Blender 4.0+](https://img.shields.io/badge/Blender-4.0%20%7C%204.1%20%7C%204.2%2B-F5792A?logo=blender&logoColor=white)](https://www.blender.org/)
[![Android 8.0+](https://img.shields.io/badge/Android-8.0%2B-3DDC84?logo=android&logoColor=white)](https://android.com)
[![UDP 120Hz](https://img.shields.io/badge/Streaming-UDP%20120Hz-00F2FE)](#architecture)
[![Languages](https://img.shields.io/badge/Languages-8%20Supported-9D4EDD)](#localization)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-Buy%20a%20Pizza-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/ctrlside)

> **Turn your smartphone or tablet into an ultra-low latency SpaceMouse and contextual workflow controller for Blender.**

BlendPad eliminates the need for expensive dedicated 3D hardware ($150–$400) by leveraging your mobile device's high-refresh multi-touch screen. With **direct 120Hz UDP coordinate streaming**, latency is imperceptible (~1.2 ms on local Wi-Fi), providing smooth and intuitive 3D viewport navigation.

---

## 🌟 Key Features

### 🕹️ Multi-Touch Viewport Navigation
- **1-Finger Drag**: Smooth Orbit around selected geometry or 3D cursor.
- **2-Finger Drag**: Pan along the viewport camera plane.
- **Pinch-to-Zoom**: Continuous, fine-grained focal scaling.
- **Numpad View Snapping**: Instant 1-tap switching to Front (1), Right (3), Top (7), Bottom, Left, Back, and Camera (0).

### ⚡ 120Hz UDP Direct Streaming
- Zero cloud relay: All communication stays 100% inside your local Wi-Fi network.
- Delta coordinates are packed into compact binary UDP datagrams processed at high frequency on the Blender event loop.
- Secondary persistent TCP channel handles high-reliability mode handshakes and discrete macro commands.

### 🎛️ Mode-Aware Dynamic Decks
BlendPad continuously listens to Blender's state and shifts its on-screen buttons automatically:
- **Object Mode**: Align, Origin to Geometry, Apply Transforms, Quick Duplicate.
- **Sculpt Mode**: Clay Strips, Draw, Grab, Smooth, Dyntopo toggles, Voxel Remesh, X-Symmetry.
- **Edit Mesh Mode**: Vertex / Edge / Face selection filters, Extrude Region (E), Bevel (Ctrl+B), Loop Cut (Ctrl+R), Knife (K), Inset (I).
- **Shading & Lighting**: Wireframe, Solid, Material Preview, Cycles/EEVEE Render toggles, Local View isolate.
- **Animation & Timeline**: Continuous scrubber dial, Play/Pause, Keyframe insertion (Loc/Rot/Scale).

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

### Step 1: Install Blender Add-on
1. Download [`blendpad_blender.zip`](releases/blendpad_blender.zip).
2. Open Blender (4.0, 4.1, or 4.2+).
3. Go to **Edit > Preferences > Add-ons**.
4. Click **Install from Disk** (top-right) and select `blendpad_blender.zip`.
5. Check the box to enable **BlendPad Direct**.

### Step 2: Start the Daemon
1. In the 3D Viewport, press **`N`** to open the right sidebar.
2. Select the **BlendPad** tab.
3. Click **Avvia Server**. A QR code overlay will appear in the viewport.

### Step 3: Launch BlendPad Mobile
1. Install and open the BlendPad app on your Android device ([download APK](releases/blendpad_mobile.apk)).
2. Tap **Scan QR** and point your camera at the QR code in Blender.
3. You're connected! Use your phone screen to orbit, pan, zoom, and trigger shortcuts.

---

## 📊 Free vs Studio PRO

| Feature | Free | Studio PRO |
|---|:---:|:---:|
| 120Hz UDP Touchpad (Orbit, Pan, Zoom) | ✅ | ✅ |
| Standard Numpad View Snapping | ✅ | ✅ |
| QR Pairing & Local Token Security | ✅ | ✅ |
| Standard Dynamic Mode Workflows | ✅ | ✅ |
| Interactive Rotary Dials & Precision Continuous Sliders | — | ✅ |
| Custom Drag-and-Drop Button Layout Designer | — | ✅ |
| Custom Python Operators & Blender Macros | — | ✅ |
| Advanced Timeline Scrubbing & Node Editor Decks | — | ✅ |

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

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
Blender is a registered trademark of the Blender Foundation.
