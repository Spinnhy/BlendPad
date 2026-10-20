bl_info = {
    "name": "BlendPad Direct",
    "author": "BlendPad",
    "version": (1, 4, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > BlendPad",
    "description": "Ultra-low latency SpaceMouse & Viewport Controller for Mobile via Direct UDP/TCP",
    "category": "3D View",
}

ADDON_VERSION = "1.4.0"
MIN_APP_VERSION = "1.0.0"
PROTOCOL_VERSION = 3

import bpy
from bpy.props import FloatProperty, IntProperty, BoolProperty, StringProperty, PointerProperty
from bpy.types import Panel, Operator, PropertyGroup
import mathutils
from mathutils import Quaternion, Vector, Euler
import socket
import threading
import struct
import json
import math
import time
import os
import tempfile
import secrets
import gpu
from gpu_extras.batch import batch_for_shader
try:
    from . import qr_code
except (ImportError, ValueError):
    import qr_code

# Global Server State
class CADPadState:
    running = False
    udp_thread = None
    tcp_thread = None
    udp_sock = None
    tcp_sock = None
    active_client = None
    active_client_addr = None
    client_lock = threading.Lock()
    
    # Delta Accumulator (thread-safe)
    acc_lock = threading.Lock()
    orbit_x = 0.0
    orbit_y = 0.0
    pan_x = 0.0
    pan_y = 0.0
    zoom = 0.0
    
    # Queue for discrete commands from TCP
    cmd_queue = []
    cmd_lock = threading.Lock()
    
    # Mode & Workflow tracking
    last_mode = None
    last_mode_check = 0.0
    mouse_x = -1
    mouse_y = -1
    tracker_running = False
    
    # Stats
    packets_received = 0
    connected_ip = ""
    local_ip = "127.0.0.1"
    qr_file_path = ""

    # Pairing token & QR overlay
    token = ""
    qr_payload = ""
    qr_matrix = None
    qr_overlay_handle = None
    qr_batch_cache = None
    qr_hide_pending = False


state = CADPadState()


def _token_file_path():
    try:
        cfg = bpy.utils.user_resource('CONFIG', path="cadpad", create=True)
    except Exception:
        cfg = tempfile.gettempdir()
    return os.path.join(cfg, "pairing_token.txt")


def load_or_create_token(regenerate=False):
    """Persistent pairing token, stored in Blender user config (survives restarts)."""
    path = _token_file_path()
    if not regenerate:
        try:
            with open(path, "r", encoding="utf-8") as f:
                tok = f.read().strip()
            if len(tok) >= 8:
                state.token = tok
                return tok
        except Exception:
            pass
    tok = secrets.token_hex(8)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(tok)
    except Exception as e:
        print(f"[CADPad] Cannot save token: {e}")
    state.token = tok
    return tok


def get_local_lan_ip():
    """Finds the LAN IP facing external devices."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# --- Network Servers ---

def udp_worker(udp_port):
    """UDP listener for high-frequency binary stream (16 bytes) and discovery."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", udp_port))
        sock.settimeout(0.5)
        state.udp_sock = sock
    except Exception as e:
        print(f"[CADPad] UDP Bind Error on {udp_port}: {e}")
        return

    print(f"[CADPad] UDP Server listening on 0.0.0.0:{udp_port}")
    
    while state.running:
        try:
            data, addr = sock.recvfrom(128)
            if not data:
                continue
                
            # Discovery Broadcast (type 0xF0)
            if len(data) >= 2 and data[0] == 0xCF and data[1] == 0xF0:
                payload = json.dumps({
                    "name": socket.gethostname(),
                    "blender": f"{bpy.app.version[0]}.{bpy.app.version[1]}",
                    "proto": 2,
                    "tcp": bpy.context.scene.cadpad_props.tcp_port if hasattr(bpy.context.scene, "cadpad_props") else 4243
                }).encode('utf-8')
                resp = bytes([0xCF, 0xF1]) + payload
                sock.sendto(resp, addr)
                continue

            # Standard 16-byte Stream Packet
            if len(data) == 16 and data[0] == 0xCF:
                cmd_type, seq, p1, p2, flags = struct.unpack('<BBHffi', data[:16])
                mult = 0.1 if (flags & 1) else 1.0
                
                with state.acc_lock:
                    state.packets_received += 1
                    if cmd_type == 0x01: # ORBIT
                        state.orbit_x += p1 * mult
                        state.orbit_y += p2 * mult
                    elif cmd_type == 0x02: # PAN
                        state.pan_x += p1 * mult
                        state.pan_y += p2 * mult
                    elif cmd_type == 0x03: # ZOOM
                        state.zoom += p1 * mult

        except socket.timeout:
            continue
        except Exception:
            pass
                
    try:
        sock.close()
    except Exception:
        pass


def handle_tcp_client(conn, addr):
    """Handles an active TCP control session."""
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(1.0)
    
    print(f"[CADPad] TCP Client connecting: {addr} (awaiting token)")
    authed = False
    auth_deadline = time.time() + 5.0
        
    buffer = ""
    while state.running:
        with state.client_lock:
            if state.active_client != conn:
                break
                
        if not authed and time.time() > auth_deadline:
            print(f"[CADPad] Auth timeout from {addr}")
            break

        try:
            chunk = conn.recv(2048)
            if not chunk:
                break
            buffer += chunk.decode('utf-8', errors='ignore')
            
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    msg_id = msg.get("id")
                    msg_type = msg.get("type")

                    # --- Authentication gate ---
                    if not authed:
                        if msg_type == "hello" and secrets.compare_digest(str(msg.get("token", "")), state.token):
                            authed = True
                            state.connected_ip = addr[0]
                            state.last_mode = None  # force mode push
                            state.qr_hide_pending = True
                            client_app_ver = str(msg.get("app_version", "1.0.0"))
                            welcome = json.dumps({
                                "type": "welcome",
                                "proto": PROTOCOL_VERSION,
                                "addon_version": ADDON_VERSION,
                                "min_app_version": MIN_APP_VERSION,
                                "blender": f"{bpy.app.version[0]}.{bpy.app.version[1]}.{bpy.app.version[2]}",
                                "mode": bpy.context.mode if bpy.context else "OBJECT",
                            }) + "\n"
                            conn.sendall(welcome.encode('utf-8'))
                            print(f"[CADPad] Client authenticated: {addr} (App v{client_app_ver}, Add-on v{ADDON_VERSION})")
                        else:
                            conn.sendall((json.dumps({"type": "auth_error"}) + "\n").encode('utf-8'))
                            print(f"[CADPad] Rejected client {addr}: invalid token")
                            raise ConnectionAbortedError()
                        continue
                    
                    # Motion over TCP
                    if msg_type == "orbit":
                        dx = float(msg.get("dx", 0.0))
                        dy = float(msg.get("dy", 0.0))
                        with state.acc_lock:
                            state.orbit_x += dx
                            state.orbit_y += dy
                    elif msg_type == "pan":
                        dx = float(msg.get("dx", 0.0))
                        dy = float(msg.get("dy", 0.0))
                        with state.acc_lock:
                            state.pan_x += dx
                            state.pan_y += dy
                    elif msg_type == "zoom":
                        dz = float(msg.get("dz", 0.0))
                        with state.acc_lock:
                            state.zoom += dz
                            
                    # Discrete Controls
                    elif msg_type == "ping":
                        resp = json.dumps({"type": "pong", "id": msg_id}) + "\n"
                        conn.sendall(resp.encode('utf-8'))
                    elif msg_type == "view":
                        target = msg.get("target")
                        with state.cmd_lock:
                            state.cmd_queue.append(("view", target))
                        resp = json.dumps({"type": "ack", "id": msg_id, "ok": True}) + "\n"
                        conn.sendall(resp.encode('utf-8'))
                    elif msg_type in ("undo", "redo"):
                        with state.cmd_lock:
                            state.cmd_queue.append((msg_type, None))
                        resp = json.dumps({"type": "ack", "id": msg_id, "ok": True}) + "\n"
                        conn.sendall(resp.encode('utf-8'))
                        
                    # Sculpt Tools
                    elif msg_type == "sculpt_brush_size":
                        delta = float(msg.get("delta", 0.0))
                        with state.cmd_lock:
                            state.cmd_queue.append(("brush_size", delta))
                    elif msg_type == "sculpt_brush_strength":
                        delta = float(msg.get("delta", 0.0))
                        with state.cmd_lock:
                            state.cmd_queue.append(("brush_strength", delta))
                    elif msg_type == "sculpt_brush_invert":
                        with state.cmd_lock:
                            state.cmd_queue.append(("brush_invert", None))
                            
                    # Edit Mesh Tools
                    elif msg_type == "edit_action":
                        action = msg.get("action")
                        with state.cmd_lock:
                            state.cmd_queue.append(("edit_action", action))
                    elif msg_type == "select_mode":
                        mode_sel = msg.get("mode")
                        with state.cmd_lock:
                            state.cmd_queue.append(("select_mode", mode_sel))

                    # Animation Tools
                    elif msg_type == "anim_play_pause":
                        with state.cmd_lock:
                            state.cmd_queue.append(("anim_play_pause", None))
                    elif msg_type == "anim_keyframe_jump":
                        is_next = bool(msg.get("next", True))
                        with state.cmd_lock:
                            state.cmd_queue.append(("anim_keyframe_jump", is_next))
                    elif msg_type == "anim_keyframe_insert":
                        with state.cmd_lock:
                            state.cmd_queue.append(("anim_keyframe_insert", None))
                    elif msg_type == "anim_frame_step":
                        delta = int(msg.get("delta", 1))
                        with state.cmd_lock:
                            state.cmd_queue.append(("anim_frame_step", delta))

                    # Node Editor Tools
                    elif msg_type == "node_action":
                        action = msg.get("action")
                        with state.cmd_lock:
                            state.cmd_queue.append(("node_action", action))

                    # Shading & Render Tools
                    elif msg_type == "shading_set":
                        shading = msg.get("shading")
                        with state.cmd_lock:
                            state.cmd_queue.append(("shading_set", shading))
                    elif msg_type == "render_action":
                        action = msg.get("action")
                        with state.cmd_lock:
                            state.cmd_queue.append(("render_action", action))

                    # Transforms & Pose
                    elif msg_type == "transform_action":
                        action = msg.get("action")
                        with state.cmd_lock:
                            state.cmd_queue.append(("transform_action", action))
                    elif msg_type == "pose_action":
                        action = msg.get("action")
                        with state.cmd_lock:
                            state.cmd_queue.append(("pose_action", action))

                    # Paint Tools
                    elif msg_type == "paint_action":
                        action = msg.get("action")
                        with state.cmd_lock:
                            state.cmd_queue.append(("paint_action", action))

                    # Custom Operator
                    elif msg_type == "custom_op":
                        op_name = msg.get("op")
                        op_args = msg.get("args", {})
                        with state.cmd_lock:
                            state.cmd_queue.append(("custom_op", (op_name, op_args)))
                            
                    else:
                        resp = json.dumps({"type": "ack", "id": msg_id, "ok": True}) + "\n"
                        conn.sendall(resp.encode('utf-8'))
                except ConnectionAbortedError:
                    raise
                except Exception as e:
                    print(f"[CADPad] JSON parse error: {e}")
                    
        except socket.timeout:
            continue
        except Exception:
            break
            
    try:
        conn.close()
    except Exception:
        pass
        
    with state.client_lock:
        if state.active_client == conn:
            state.active_client = None
            state.connected_ip = ""
    print(f"[CADPad] TCP Client disconnected: {addr}")


def tcp_worker(tcp_port):
    """TCP server listener for control connection."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", tcp_port))
        sock.listen(1)
        sock.settimeout(0.5)
        state.tcp_sock = sock
    except Exception as e:
        print(f"[CADPad] TCP Bind Error on {tcp_port}: {e}")
        return

    print(f"[CADPad] TCP Server listening on 0.0.0.0:{tcp_port}")
    
    while state.running:
        try:
            conn, addr = sock.accept()
            with state.client_lock:
                if state.active_client:
                    try:
                        state.active_client.close()
                    except Exception:
                        pass
                state.active_client = conn
                state.active_client_addr = addr
                
            client_thread = threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True)
            client_thread.start()
        except socket.timeout:
            continue
        except Exception:
            pass
                
    try:
        sock.close()
    except Exception:
        pass


# --- Main Thread Viewport Timer (120 Hz) ---

def find_primary_3d_view():
    """Finds the largest 3D Viewport in current screen."""
    wm = bpy.context.window_manager
    if not wm or not wm.windows:
        return None, None, None
        
    for win in wm.windows:
        screen = win.screen
        if not screen:
            continue
        best_area = None
        best_size = 0
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                size = area.width * area.height
                if size > best_size:
                    best_size = size
                    best_area = area
        if best_area:
            region = next((r for r in best_area.regions if r.type == 'WINDOW'), None)
            return win, best_area, region
            
    return None, None, None


def execute_view_command(win, area, region, target):
    """Executes canonical view changes with proper context override."""
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            if target in ("TOP", "BOTTOM", "FRONT", "BACK", "RIGHT", "LEFT"):
                bpy.ops.view3d.view_axis(type=target)
            elif target == "CAMERA":
                bpy.ops.view3d.view_camera()
            elif target == "ORTHO_TOGGLE":
                bpy.ops.view3d.view_persportho()
            elif target == "FRAME_SELECTED":
                bpy.ops.view3d.view_selected()
    except Exception as e:
        print(f"[CADPad] View command '{target}' error: {e}")


def execute_sculpt_edit_command(win, area, region, cmd_type, arg):
    """Executes sculpt and edit operations with direct property access."""
    try:
        ts = bpy.context.tool_settings
        
        # Sculpt Commands
        if cmd_type == "brush_size":
            sc = getattr(ts, "sculpt", None)
            if sc:
                ups = getattr(sc, "unified_paint_settings", None)
                curr = 50
                if ups and hasattr(ups, "size"):
                    curr = ups.size
                elif sc.brush and hasattr(sc.brush, "size"):
                    curr = sc.brush.size

                # Exponential radius scaling:
                # Smaller radius = finer sensitivity, larger radius = higher sensitivity
                factor = math.exp(arg * 0.005)
                diff = curr * factor - curr
                if abs(diff) < 1.0:
                    diff = 1.0 if arg > 0 else -1.0
                new_size = max(1, min(5000, int(round(curr + diff))))

                if ups and hasattr(ups, "size"):
                    ups.size = new_size
                if sc.brush and hasattr(sc.brush, "size"):
                    sc.brush.size = new_size
                    
        elif cmd_type == "brush_strength":
            sc = getattr(ts, "sculpt", None)
            if sc:
                ups = getattr(sc, "unified_paint_settings", None)
                if ups and hasattr(ups, "strength"):
                    ups.strength = max(0.01, min(1.0, ups.strength + arg))
                if sc.brush and hasattr(sc.brush, "strength"):
                    sc.brush.strength = max(0.01, min(1.0, sc.brush.strength + arg))
                    
        elif cmd_type == "brush_invert":
            sc = getattr(ts, "sculpt", None)
            if sc and sc.brush and hasattr(sc.brush, "direction"):
                sc.brush.direction = 'SUBTRACT' if sc.brush.direction == 'ADD' else 'ADD'
                
        # Edit Mesh Selection Mode (Direct property, never fails)
        elif cmd_type == "select_mode":
            if arg == "VERT":
                ts.mesh_select_mode = (True, False, False)
            elif arg == "EDGE":
                ts.mesh_select_mode = (False, True, False)
            elif arg == "FACE":
                ts.mesh_select_mode = (False, False, True)
                
        # Edit Mesh Operators (interactive: follow the mouse like the keyboard shortcut)
        elif cmd_type == "edit_action":
            run_edit_operator(win, area, region, arg)
                    
    except Exception as e:
        print(f"[CADPad] Tool execution error: {e}")


# (interactive operator, fallback non-interactive operator)
EDIT_OPERATORS = {
    "EXTRUDE": (("view3d", "edit_mesh_extrude_move_normal", {}), ("mesh", "extrude_region_move", {})),
    "BEVEL": (("mesh", "bevel", {}), ("mesh", "bevel", {"offset": 0.1})),
    "INSET": (("mesh", "inset", {}), ("mesh", "inset", {"thickness": 0.05})),
    "SUBDIVIDE": (None, ("mesh", "subdivide", {})),
}


def run_edit_operator(win, area, region, action):
    spec = EDIT_OPERATORS.get(action)
    if not spec:
        print(f"[CADPad] Unknown edit action: {action}")
        return
    interactive, fallback = spec
    if bpy.context.mode != 'EDIT_MESH':
        print(f"[CADPad] '{action}' ignored: not in Edit Mesh mode")
        return
    with bpy.context.temp_override(window=win, area=area, region=region):
        if interactive:
            cat, name, kw = interactive
            try:
                op = getattr(getattr(bpy.ops, cat), name)
                res = op('INVOKE_DEFAULT', **kw)
                print(f"[CADPad] {action} interactive -> {res}")
                if 'CANCELLED' not in res:
                    return
            except Exception as e:
                print(f"[CADPad] {action} interactive failed: {e}")
        cat, name, kw = fallback
        try:
            op = getattr(getattr(bpy.ops, cat), name)
            res = op('EXEC_DEFAULT', **kw)
            print(f"[CADPad] {action} exec -> {res}")
        except Exception as e:
            print(f"[CADPad] {action} exec failed: {e}")


def execute_anim_command(win, area, region, cmd_type, arg):
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            if cmd_type == "anim_play_pause":
                bpy.ops.screen.animation_play()
            elif cmd_type == "anim_keyframe_jump":
                bpy.ops.screen.keyframe_jump(next=bool(arg))
            elif cmd_type == "anim_keyframe_insert":
                try:
                    bpy.ops.anim.keyframe_insert_menu(type='Available')
                except Exception:
                    bpy.ops.anim.keyframe_insert()
            elif cmd_type == "anim_frame_step":
                scene = bpy.context.scene
                step = int(arg)
                scene.frame_set(max(scene.frame_start, min(scene.frame_end, scene.frame_current + step)))
    except Exception as e:
        print(f"[CADPad] Animation error: {e}")


def execute_node_command(win, area, region, action):
    node_area = None
    node_region = None
    if win and win.screen:
        for a in win.screen.areas:
            if a.type == 'NODE_EDITOR':
                node_area = a
                node_region = next((r for r in a.regions if r.type == 'WINDOW'), None)
                break
    
    target_area = node_area if node_area else area
    target_region = node_region if node_region else region

    try:
        with bpy.context.temp_override(window=win, area=target_area, region=target_region):
            if action == "ADD":
                bpy.ops.wm.call_menu(name="NODE_MT_add")
            elif action == "VIEW_SELECTED":
                bpy.ops.node.view_selected()
            elif action == "DELETE":
                bpy.ops.node.delete()
            elif action == "MUTE":
                bpy.ops.node.mute_toggle()
    except Exception as e:
        print(f"[CADPad] Node action error: {e}")


def execute_shading_render_command(win, area, region, cmd_type, arg):
    try:
        if cmd_type == "shading_set":
            if area and area.spaces and area.spaces.active and hasattr(area.spaces.active, "shading"):
                area.spaces.active.shading.type = str(arg).upper()
        elif cmd_type == "render_action":
            with bpy.context.temp_override(window=win, area=area, region=region):
                if arg == "IMAGE":
                    bpy.ops.render.render('INVOKE_DEFAULT')
                elif arg == "ANIMATION":
                    bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
                elif arg == "CAMERA":
                    bpy.ops.view3d.view_camera()
    except Exception as e:
        print(f"[CADPad] Shading/Render error: {e}")


def execute_transform_command(win, area, region, action):
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            if action == "TRANSLATE":
                bpy.ops.transform.translate('INVOKE_DEFAULT')
            elif action == "ROTATE":
                bpy.ops.transform.rotate('INVOKE_DEFAULT')
            elif action == "RESIZE":
                bpy.ops.transform.resize('INVOKE_DEFAULT')
    except Exception as e:
        print(f"[CADPad] Transform error: {e}")


def execute_pose_command(win, area, region, action):
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            if action == "CLEAR_ALL":
                try:
                    bpy.ops.pose.transforms_clear()
                except Exception:
                    bpy.ops.pose.loc_clear()
                    bpy.ops.pose.rot_clear()
                    bpy.ops.pose.scale_clear()
            elif action == "KEYFRAME":
                bpy.ops.anim.keyframe_insert_menu(type='Available')
    except Exception as e:
        print(f"[CADPad] Pose error: {e}")


def execute_paint_command(win, area, region, action):
    try:
        with bpy.context.temp_override(window=win, area=area, region=region):
            if action == "SAMPLE":
                bpy.ops.paint.sample_color('INVOKE_DEFAULT')
            elif action == "INVERT":
                execute_sculpt_edit_command(win, area, region, "brush_invert", None)
    except Exception as e:
        print(f"[CADPad] Paint action error: {e}")


def execute_custom_operator(win, area, region, op_data):
    try:
        op_name, op_args = op_data
        if not op_name or not isinstance(op_name, str):
            return
        parts = op_name.strip().split(".")
        if len(parts) == 2 and parts[0].isidentifier() and parts[1].isidentifier():
            cat, name = parts
            if hasattr(bpy.ops, cat) and hasattr(getattr(bpy.ops, cat), name):
                op = getattr(getattr(bpy.ops, cat), name)
                with bpy.context.temp_override(window=win, area=area, region=region):
                    kwargs = op_args if isinstance(op_args, dict) else {}
                    op('INVOKE_DEFAULT', **kwargs)
    except Exception as e:
        print(f"[CADPad] Custom operator error: {e}")


def get_area_under_mouse(win):
    """Finds which area and window region the mouse is currently hovering over."""
    if not win or not win.screen:
        return None, None
    mx, my = state.mouse_x, state.mouse_y
    if mx >= 0 and my >= 0:
        for a in win.screen.areas:
            if a.x <= mx <= a.x + a.width and a.y <= my <= a.y + a.height:
                r = next((reg for reg in a.regions if reg.type == 'WINDOW'), None)
                return a, r

    # Fallback to largest 3D view
    _, a, r = find_primary_3d_view()
    return a, r


def detect_current_workflow(win, area):
    """Determines the active workflow (NODE_EDITOR, ANIMATION, SCULPT, EDIT_MESH, etc.)."""
    if area:
        if area.type == 'NODE_EDITOR':
            return 'NODE_EDITOR'
        if area.type in ('DOPESHEET_EDITOR', 'TIMELINE', 'GRAPH_EDITOR', 'NLA_EDITOR'):
            return 'ANIMATION'
        if area.type == 'IMAGE_EDITOR':
            if bpy.context.mode == 'PAINT_TEXTURE':
                return 'PAINT_TEXTURE'
            return 'PAINT_TEXTURE'
        if area.type == 'VIEW_3D':
            mode = bpy.context.mode
            if mode in ('SCULPT', 'EDIT_MESH', 'PAINT_TEXTURE', 'PAINT_WEIGHT', 'PAINT_VERTEX', 'POSE'):
                return mode
            if mode == 'OBJECT':
                ws = win.workspace.name.lower() if win and win.workspace else ""
                if 'render' in ws:
                    return 'RENDER'
                if 'anim' in ws:
                    return 'ANIMATION'
                if 'shading' in ws or 'node' in ws:
                    return 'NODE_EDITOR'
                return 'OBJECT'

    # Fallback to workspace or mode
    ws = win.workspace.name.lower() if win and win.workspace else ""
    if 'render' in ws:
        return 'RENDER'
    if 'anim' in ws:
        return 'ANIMATION'
    if 'shading' in ws or 'node' in ws:
        return 'NODE_EDITOR'
    return bpy.context.mode if bpy.context.mode else 'OBJECT'


def cadpad_viewport_timer():
    """Timer running at ~120 Hz on Blender's main thread."""
    if not state.running:
        return None

    wm = bpy.context.window_manager
    win = wm.windows[0] if wm and wm.windows else None
    if not win:
        return 0.008

    # Ensure mouse tracker is running
    if not state.tracker_running:
        try:
            bpy.ops.cadpad.mouse_tracker('INVOKE_DEFAULT')
        except Exception:
            pass

    target_area, target_region = get_area_under_mouse(win)
    if not target_area:
        _, target_area, target_region = find_primary_3d_view()
        if not target_area:
            return 0.008

    is_2d_editor = target_area.type in (
        'NODE_EDITOR', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR',
        'NLA_EDITOR', 'IMAGE_EDITOR', 'SEQUENCE_EDITOR', 'CLIP_EDITOR'
    )

    props = bpy.context.scene.cadpad_props if hasattr(bpy.context.scene, "cadpad_props") else None
    sens_orbit = props.orbit_sensitivity if props else 0.008
    sens_pan = props.pan_sensitivity if props else 0.002
    sens_zoom = props.zoom_sensitivity if props else 0.02

    # 1. Consume accumulated deltas
    with state.acc_lock:
        dx, dy = state.orbit_x, state.orbit_y
        px, py = state.pan_x, state.pan_y
        dz = state.zoom
        state.orbit_x, state.orbit_y = 0.0, 0.0
        state.pan_x, state.pan_y = 0.0, 0.0
        state.zoom = 0.0

    needs_redraw = False

    if is_2d_editor and target_region:
        # === 2D Navigation (Node Editor, Timeline, Graph Editor, etc.) ===
        # 1-finger Orbit / Pan gesture in 2D
        if dx != 0.0 or dy != 0.0:
            try:
                with bpy.context.temp_override(window=win, area=target_area, region=target_region):
                    bpy.ops.view2d.pan('EXEC_DEFAULT', deltax=int(round(-dx * 1.5)), deltay=int(round(dy * 1.5)))
                    needs_redraw = True
            except Exception:
                pass

        # 2-finger Pan gesture in 2D
        if px != 0.0 or py != 0.0:
            try:
                with bpy.context.temp_override(window=win, area=target_area, region=target_region):
                    bpy.ops.view2d.pan('EXEC_DEFAULT', deltax=int(round(-px * 1.5)), deltay=int(round(-py * 1.5)))
                    needs_redraw = True
            except Exception:
                pass

        # 2-finger Zoom gesture in 2D
        if dz != 0.0:
            try:
                with bpy.context.temp_override(window=win, area=target_area, region=target_region):
                    bpy.ops.view2d.zoom('EXEC_DEFAULT', deltax=0, deltay=int(round(dz * 8.0)))
                    needs_redraw = True
            except Exception:
                pass

    elif target_area.type == 'VIEW_3D':
        # === 3D Navigation (3D Viewport) ===
        r3d = target_area.spaces.active.region_3d if target_area.spaces and target_area.spaces.active else None
        if r3d:
            # Apply Orbit (Turntable: Z-global and X-local)
            if dx != 0.0 or dy != 0.0:
                if getattr(r3d, "is_orthographic_side_view", False):
                    r3d.is_orthographic_side_view = False
                if r3d.view_perspective == 'CAMERA':
                    r3d.view_perspective = 'PERSP'

                rot_z = Quaternion((0.0, 0.0, 1.0), -dx * sens_orbit)
                rot_x = Quaternion((1.0, 0.0, 0.0), -dy * sens_orbit)
                r3d.view_rotation = (rot_z @ r3d.view_rotation @ rot_x).normalized()
                needs_redraw = True

            # Apply Pan
            if px != 0.0 or py != 0.0:
                scale = r3d.view_distance * sens_pan
                pan_vec = Vector((-px * scale, -py * scale, 0.0))
                r3d.view_location += r3d.view_rotation @ pan_vec
                needs_redraw = True

            # Apply Zoom
            if dz != 0.0:
                r3d.view_distance = max(0.001, r3d.view_distance * math.exp(-dz * sens_zoom))
                needs_redraw = True

    # 2. Execute discrete commands
    with state.cmd_lock:
        cmds = list(state.cmd_queue)
        state.cmd_queue.clear()
        
    for cmd_type, arg in cmds:
        if cmd_type == "view":
            execute_view_command(win, target_area, target_region, arg)
            needs_redraw = True
        elif cmd_type in ("brush_size", "brush_strength", "brush_invert", "select_mode", "edit_action"):
            execute_sculpt_edit_command(win, target_area, target_region, cmd_type, arg)
            needs_redraw = True
        elif cmd_type.startswith("anim_"):
            execute_anim_command(win, target_area, target_region, cmd_type, arg)
            needs_redraw = True
        elif cmd_type == "node_action":
            execute_node_command(win, target_area, target_region, arg)
            needs_redraw = True
        elif cmd_type in ("shading_set", "render_action"):
            execute_shading_render_command(win, target_area, target_region, cmd_type, arg)
            needs_redraw = True
        elif cmd_type == "transform_action":
            execute_transform_command(win, target_area, target_region, arg)
            needs_redraw = True
        elif cmd_type == "pose_action":
            execute_pose_command(win, target_area, target_region, arg)
            needs_redraw = True
        elif cmd_type == "paint_action":
            execute_paint_command(win, target_area, target_region, arg)
            needs_redraw = True
        elif cmd_type == "custom_op":
            execute_custom_operator(win, target_area, target_region, arg)
            needs_redraw = True
        elif cmd_type == "undo":
            try:
                bpy.ops.ed.undo()
                needs_redraw = True
            except Exception:
                pass
        elif cmd_type == "redo":
            try:
                bpy.ops.ed.redo()
                needs_redraw = True
            except Exception:
                pass

    if needs_redraw:
        target_area.tag_redraw()
        if target_region:
            target_region.tag_redraw()
        if win and win.screen:
            for a in win.screen.areas:
                if a.type in ('VIEW_3D', 'NODE_EDITOR', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'PROPERTIES', 'TOPBAR'):
                    a.tag_redraw()

    # 3. Contextual Workflow Sync Check (~4 Hz)
    now = time.time()
    if now - state.last_mode_check > 0.25:
        state.last_mode_check = now
        curr_workflow = detect_current_workflow(win, target_area)
        if curr_workflow != state.last_mode:
            state.last_mode = curr_workflow
            with state.client_lock:
                if state.active_client:
                    try:
                        msg = json.dumps({"type": "mode", "mode": curr_workflow}) + "\n"
                        state.active_client.sendall(msg.encode('utf-8'))
                    except Exception:
                        pass

    # 3b. Auto-hide pairing QR once the phone is authenticated
    if state.qr_hide_pending:
        state.qr_hide_pending = False
        set_qr_overlay(False)

    return 0.008


# --- QR Code & UI Operators ---

def _draw_qr_overlay():
    """Draws the pairing QR code directly on top of the 3D viewport."""
    if state.qr_matrix is None:
        return
    region = bpy.context.region
    if region is None:
        return
    n = len(state.qr_matrix)
    margin = 4
    side = min(region.width, region.height) * 0.6
    cell = side / (n + 2 * margin)
    x0 = (region.width - side) / 2
    y0 = (region.height - side) / 2

    key = (n, round(x0, 1), round(y0, 1), round(cell, 3), state.qr_payload)
    if state.qr_batch_cache is None or state.qr_batch_cache[0] != key:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        bg = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
        bg_batch = batch_for_shader(shader, 'TRIS', {"pos": bg}, indices=[(0, 1, 2), (0, 2, 3)])
        verts, idx = [], []
        for r in range(n):
            for c in range(n):
                if state.qr_matrix[r][c]:
                    px = x0 + (c + margin) * cell
                    py = y0 + side - (r + margin + 1) * cell
                    b = len(verts)
                    verts += [(px, py), (px + cell, py), (px + cell, py + cell), (px, py + cell)]
                    idx += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
        fg_batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=idx)
        state.qr_batch_cache = (key, shader, bg_batch, fg_batch)

    _, shader, bg_batch, fg_batch = state.qr_batch_cache
    gpu.state.blend_set('NONE')
    shader.bind()
    shader.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
    bg_batch.draw(shader)
    shader.uniform_float("color", (0.0, 0.0, 0.0, 1.0))
    fg_batch.draw(shader)


def set_qr_overlay(enabled):
    if enabled and state.qr_overlay_handle is None:
        state.qr_overlay_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_qr_overlay, (), 'WINDOW', 'POST_PIXEL')
    elif not enabled and state.qr_overlay_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(state.qr_overlay_handle, 'WINDOW')
        state.qr_overlay_handle = None
    try:
        for win in bpy.context.window_manager.windows:
            for a in win.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()
    except Exception:
        pass


def generate_qr_image_and_file(props):
    """Generates QR code BMP and loads it into Blender images and properties."""
    state.local_ip = get_local_lan_ip()
    if not state.token:
        load_or_create_token()
    payload = f"cadpad://{state.local_ip}?udp={props.udp_port}&tcp={props.tcp_port}&token={state.token}"
    state.qr_payload = payload
    state.qr_matrix = qr_code.generate_qr_matrix(payload)
    state.qr_batch_cache = None
    
    tmp_dir = tempfile.gettempdir()
    state.qr_file_path = os.path.join(tmp_dir, "cadpad_qr.bmp")
    
    try:
        qr_code.save_qr_bmp(state.qr_file_path, payload, scale=6)
        
        # Load or reload into Blender bpy.data.images
        img_name = "CADPad_QR_Image"
        if img_name in bpy.data.images:
            img = bpy.data.images[img_name]
            img.reload()
        else:
            img = bpy.data.images.load(state.qr_file_path)
            img.name = img_name
            
        img.preview_ensure()
        props.qr_image = img
        print(f"[CADPad] QR Code generated successfully for {state.local_ip}")
    except Exception as e:
        print(f"[CADPad] Error generating QR code: {e}")


class CADPAD_OT_toggle_qr_overlay(Operator):
    bl_idname = "cadpad.toggle_qr_overlay"
    bl_label = "Mostra/Nascondi QR nella Viewport"
    bl_description = "Disegna il QR Code di abbinamento al centro della Viewport 3D"

    def execute(self, context):
        if state.qr_matrix is None:
            generate_qr_image_and_file(context.scene.cadpad_props)
        set_qr_overlay(state.qr_overlay_handle is None)
        return {'FINISHED'}


class CADPAD_OT_regenerate_token(Operator):
    bl_idname = "cadpad.regenerate_token"
    bl_label = "Rigenera Token"
    bl_description = "Crea un nuovo token di sicurezza: i telefoni già abbinati dovranno riscansionare il QR"

    def execute(self, context):
        load_or_create_token(regenerate=True)
        generate_qr_image_and_file(context.scene.cadpad_props)
        with state.client_lock:
            if state.active_client:
                try:
                    state.active_client.close()
                except Exception:
                    pass
                state.active_client = None
                state.connected_ip = ""
        self.report({'INFO'}, "Nuovo token generato: riscansiona il QR")
        return {'FINISHED'}


class CADPAD_OT_open_qr_window(Operator):
    bl_idname = "cadpad.open_qr_window"
    bl_label = "Apri QR Code a Schermo Intero"
    bl_description = "Apre l'immagine del QR Code a schermo intero per una scansione immediata"

    def execute(self, context):
        if not state.qr_file_path or not os.path.exists(state.qr_file_path):
            generate_qr_image_and_file(context.scene.cadpad_props)
            
        if os.path.exists(state.qr_file_path):
            # Open file in default image viewer or browser
            bpy.ops.wm.url_open(url=f"file://{state.qr_file_path}")
            self.report({'INFO'}, "QR Code aperto nel visualizzatore")
        else:
            self.report({'ERROR'}, "Impossibile generare file QR")
        return {'FINISHED'}


class CADPAD_OT_mouse_tracker(Operator):
    bl_idname = "cadpad.mouse_tracker"
    bl_label = "BlendPad Mouse Tracker"
    bl_description = "Traccia passivamente la posizione del mouse per la navigazione 2D/3D contestuale"

    def modal(self, context, event):
        if not state.running:
            state.tracker_running = False
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            state.mouse_x = event.mouse_x
            state.mouse_y = event.mouse_y
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        state.tracker_running = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class CADPAD_OT_start_server(Operator):
    bl_idname = "cadpad.start_server"
    bl_label = "Avvia Server BlendPad"
    bl_description = "Avvia i server UDP e TCP per connettere l'app mobile"

    def execute(self, context):
        if state.running:
            self.report({'INFO'}, "Server già in esecuzione")
            return {'FINISHED'}

        props = context.scene.cadpad_props
        load_or_create_token()
        state.running = True
        
        # Start background network threads
        state.udp_thread = threading.Thread(target=udp_worker, args=(props.udp_port,), daemon=True)
        state.tcp_thread = threading.Thread(target=tcp_worker, args=(props.tcp_port,), daemon=True)
        state.udp_thread.start()
        state.tcp_thread.start()
        
        # Register main thread viewport timer
        bpy.app.timers.register(cadpad_viewport_timer, persistent=True)
        
        # Generate QR Code and show it in the viewport for pairing
        generate_qr_image_and_file(props)
        if not state.connected_ip:
            set_qr_overlay(True)

        self.report({'INFO'}, f"BlendPad Server avviato su {state.local_ip}")
        return {'FINISHED'}


class CADPAD_OT_stop_server(Operator):
    bl_idname = "cadpad.stop_server"
    bl_label = "Arresta Server"
    bl_description = "Chiude i server di ascolto"

    def execute(self, context):
        state.running = False
        with state.client_lock:
            if state.active_client:
                try:
                    state.active_client.close()
                except Exception:
                    pass
                state.active_client = None
                
        if state.udp_sock:
            try:
                state.udp_sock.close()
            except Exception:
                pass
        if state.tcp_sock:
            try:
                state.tcp_sock.close()
            except Exception:
                pass

        state.connected_ip = ""
        set_qr_overlay(False)
        self.report({'INFO'}, "BlendPad Server arrestato")
        return {'FINISHED'}


class CADPAD_OT_refresh_qr(Operator):
    bl_idname = "cadpad.refresh_qr"
    bl_label = "Aggiorna QR Code"
    bl_description = "Rigenera il QR Code con l'indirizzo IP locale corrente"

    def execute(self, context):
        props = context.scene.cadpad_props
        generate_qr_image_and_file(props)
        self.report({'INFO'}, f"QR Code aggiornato: {state.local_ip}")
        return {'FINISHED'}


class CADPAD_OT_open_kofi(Operator):
    bl_idname = "cadpad.open_kofi"
    bl_label = "Support on Ko-fi"
    bl_description = "Support BlendPad development by buying a slice of pizza on Ko-fi!"

    def execute(self, context):
        import webbrowser
        webbrowser.open("https://ko-fi.com/ctrlside")
        return {'FINISHED'}


class CADPAD_PT_main_panel(Panel):
    bl_label = "BlendPad Controller"
    bl_idname = "CADPAD_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlendPad'

    def draw(self, context):
        layout = self.layout
        props = context.scene.cadpad_props

        # Server Control Button
        col = layout.column(align=True)
        if not state.running:
            col.operator("cadpad.start_server", text="Avvia Server", icon='PLAY')
        else:
            col.operator("cadpad.stop_server", text="Arresta Server", icon='PAUSE')

        # Status & Pairing Box
        box = layout.box()
        if state.running:
            row = box.row()
            row.label(text=f"IP PC: {state.local_ip}", icon='NETWORK_DRIVE')
            row.operator("cadpad.refresh_qr", text="", icon='FILE_REFRESH')
            
            box.label(text=f"Porte: UDP {props.udp_port} | TCP {props.tcp_port}", icon='RADIOBUT_ON')
            
            if state.connected_ip:
                box.label(text=f"Connesso: {state.connected_ip}", icon='CHECKMARK')
            else:
                box.label(text="In attesa di connessione...", icon='TIME')
                
            # QR Code Preview & Fullscreen Button
            box.separator()
            box.label(text="Pairing Smartphone:")
            qr_on = state.qr_overlay_handle is not None
            box.operator("cadpad.toggle_qr_overlay",
                         text="Nascondi QR" if qr_on else "Mostra QR nella Viewport",
                         icon='HIDE_ON' if qr_on else 'HIDE_OFF')
            
            # Button to open full-screen QR in external image viewer
            box.operator("cadpad.open_qr_window", text="Apri QR in visualizzatore esterno", icon='FULLSCREEN_ENTER')

            row = box.row()
            row.label(text=f"Token: {state.token}", icon='LOCKED')
            row.operator("cadpad.regenerate_token", text="", icon='FILE_REFRESH')
        else:
            box.label(text="Server non attivo", icon='DOT')

        # Sensitivity Settings
        layout.separator()
        col = layout.column(align=True)
        col.label(text="Sensibilità Controlli:")
        col.prop(props, "orbit_sensitivity", text="Orbita")
        col.prop(props, "pan_sensitivity", text="Pan")
        col.prop(props, "zoom_sensitivity", text="Zoom")

        # Version Info & Support
        layout.separator()
        row_kofi = layout.row(align=True)
        row_kofi.operator("cadpad.open_kofi", text="Support on Ko-fi (Pizza 🍕)", icon='HEART')

        row = layout.row()
        row.alignment = 'RIGHT'
        row.label(text=f"BlendPad v{ADDON_VERSION}", icon='INFO')


class CADPadProperties(PropertyGroup):
    udp_port: IntProperty(
        name="Porta UDP",
        default=4242,
        min=1024,
        max=65535,
        description="Porta UDP per streaming coordinate touch a 120Hz"
    )
    tcp_port: IntProperty(
        name="Porta TCP",
        default=4243,
        min=1024,
        max=65535,
        description="Porta TCP per comandi viste e sincronizzazione stato"
    )
    orbit_sensitivity: FloatProperty(
        name="Sensibilità Orbita",
        default=0.008,
        min=0.0005,
        max=0.05,
        precision=4
    )
    pan_sensitivity: FloatProperty(
        name="Sensibilità Pan",
        default=0.002,
        min=0.0001,
        max=0.02,
        precision=4
    )
    zoom_sensitivity: FloatProperty(
        name="Sensibilità Zoom",
        default=0.02,
        min=0.001,
        max=0.1,
        precision=4
    )
    qr_image: PointerProperty(
        name="QR Image",
        type=bpy.types.Image
    )


classes = (
    CADPadProperties,
    CADPAD_OT_mouse_tracker,
    CADPAD_OT_start_server,
    CADPAD_OT_stop_server,
    CADPAD_OT_refresh_qr,
    CADPAD_OT_open_qr_window,
    CADPAD_OT_toggle_qr_overlay,
    CADPAD_OT_regenerate_token,
    CADPAD_OT_open_kofi,
    CADPAD_PT_main_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cadpad_props = bpy.props.PointerProperty(type=CADPadProperties)


def unregister():
    set_qr_overlay(False)
    if state.running:
        state.running = False
        if state.udp_sock:
            state.udp_sock.close()
        if state.tcp_sock:
            state.tcp_sock.close()
            
    del bpy.types.Scene.cadpad_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
