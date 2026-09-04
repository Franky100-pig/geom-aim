"""局域网联机网络层（JSON over UDP，零第三方依赖）。

拓扑：客户端-服务器。主机在本机跑权威模拟（Match），其他玩家各自运行一份
客户端：把本地键鼠输入发给主机，收到快照后在自己屏幕上渲染。

- Host：绑定 UDP 端口，处理 join/input/leave，按固定频率广播快照，超时踢人。
- Client：连接主机（IP 或 .local 主机名），上行输入，接收快照。

MTU 处理：欢迎包只带「随机种子 + 地图尺寸」，客户端据此确定性重建同一张地图，
不传 13KB 的网格（UDP 单包放不下）。快照用 BASE64 分片，单包压到 ~1200 字节，
能在普通局域网 1500 MTU 下稳定送达；丢片则当帧丢弃、等下一帧快照即可。
"""

from __future__ import annotations

import base64
import json
import socket
import time

import config as C

# 单包原始载荷上限（字节）。BASE64(800) ≈ 1068 字符，加 JSON 外壳 ≈ 1150 字节，
# 稳稳低于以太网/WiFi 的 ~1472 字节 UDP 有效载荷上限。
MAX_FRAG = 800


def local_addresses() -> list:
    """返回本机在局域网里可能被用来加入的地址（用于房间界面提示）。"""
    out = []
    try:
        import subprocess
        raw = subprocess.run(["ipconfig", "getifaddr", "en0"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
        if raw and raw != "":
            out.append(raw)
    except Exception:
        pass
    return out


class Host:
    """主机端：托管一局权威 Match，向所有加入的客户端广播快照。"""

    def __init__(self, gmap, match: "Match", port: int = C.NET_PORT,
                 seed: int = 0, cover: bool = True):
        self.gmap = gmap
        self.match = match
        self.port = port
        self.seed = seed
        self.cover = cover
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", port))
        self.sock.settimeout(0.0)
        # addr -> {"agent": Agent, "name": str, "last": float}
        self.clients: dict = {}
        self._fid = 0

    # ---- 内部 ----
    def _send(self, addr, raw: bytes):
        try:
            self.sock.sendto(raw, addr)
        except Exception:
            pass

    def _send_obj(self, addr, obj: dict):
        """发送一个对象：能塞进单包就直接发，否则 BASE64 分片发。"""
        data = json.dumps(obj).encode("utf-8")
        if len(data) <= MAX_FRAG:
            self._send(addr, data)
            return
        self._fid = (self._fid + 1) & 0xFFFF
        fid = self._fid
        total = (len(data) + MAX_FRAG - 1) // MAX_FRAG
        for seq in range(total):
            chunk = data[seq * MAX_FRAG:(seq + 1) * MAX_FRAG]
            frag = {
                "t": "frag", "fid": fid, "total": total, "seq": seq,
                "data": base64.b64encode(chunk).decode("ascii"),
            }
            self._send(addr, json.dumps(frag).encode("utf-8"))

    def _welcome(self, addr, uid: int = 0):
        g = self.gmap
        self._send_obj(addr, {
            "t": "welcome",
            "team": 0,
            "is_local": False,
            "uid": uid,
            "seed": self.seed,
            "cover": self.cover,
            "room_w": getattr(g, "room_w", C.SCORE_MAP_ROOM_W),
            "room_h": getattr(g, "room_h", C.SCORE_MAP_ROOM_H),
            "tiles_x": getattr(g, "tiles_x", C.SCORE_MAP_TILES_X),
            "tiles_y": getattr(g, "tiles_y", C.SCORE_MAP_TILES_Y),
        })

    def _handle(self, msg, addr, now):
        t = msg.get("t")
        if t == "join":
            if addr in self.clients:
                return
            if self.match.human_count >= C.NET_MAX_HUMANS:
                self._send_obj(addr, {"t": "full"})
                return
            name = str(msg.get("name", "玩家"))[:12] or "玩家"
            a = self.match.add_human_agent(0, name)
            self.clients[addr] = {"agent": a, "name": name, "last": now}
            self._welcome(addr, a.uid)
        elif t == "input":
            info = self.clients.get(addr)
            if info is not None:
                self.match.human_inputs[info["agent"]] = msg.get("i", {})
                info["last"] = now
        elif t == "leave":
            info = self.clients.pop(addr, None)
            if info is not None:
                self.match.remove_human_agent(info["agent"])

    def poll(self, now=None):
        """处理入站数据包 + 超时踢人。每帧调一次。"""
        now = time.time() if now is None else now
        while True:
            try:
                data, addr = self.sock.recvfrom(65535)
            except (BlockingIOError, socket.timeout):
                break
            except Exception:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            self._handle(msg, addr, now)
        # 超时踢人
        for addr, info in list(self.clients.items()):
            if now - info["last"] > C.NET_TIMEOUT:
                self.match.remove_human_agent(info["agent"])
                del self.clients[addr]

    def broadcast(self, snap: dict):
        """把整局快照推送给所有客户端（自动分片）。"""
        payload = {"t": "snap", "s": snap}
        for addr in self.clients:
            self._send_obj(addr, payload)

    def names(self) -> list:
        return [info["name"] for info in self.clients.values()]

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class Client:
    """客户端：连接主机，上行输入，接收（分片）快照。"""

    def __init__(self, host: str, name: str = "你", port: int = C.NET_PORT):
        self.host = host
        self.name = name
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.0)
        self.target = self._resolve(host, port)
        self.snap = None
        self.seq = 0
        self.connected = False
        self.last_recv = time.time()   # 最后收到主机任意包的时刻（断线检测用）
        # fid -> {"total": int, "have": set, "parts": dict}
        self._frags = {}
        self._last_fid = None

    def _resolve(self, host, port):
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
            return (infos[0][4][0], port)
        except Exception:
            return (host, port)

    def _send(self, msg: dict):
        try:
            self.sock.sendto(json.dumps(msg).encode("utf-8"), self.target)
        except Exception:
            pass

    def connect(self, timeout: float = 5.0):
        """阻塞到拿到 welcome（或超时/房间满）。成功返回 welcome dict。"""
        self._send({"t": "join", "name": self.name})
        end = time.time() + timeout
        self.sock.settimeout(0.2)
        while time.time() < end:
            try:
                data, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                self._send({"t": "join", "name": self.name})
                continue
            except Exception:
                self._send({"t": "join", "name": self.name})
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            if msg.get("t") == "welcome":
                self.connected = True
                self.last_recv = time.time()
                return msg
            if msg.get("t") == "full":
                return None
        return None

    def send_input(self, inp: dict):
        self.seq += 1
        self._send({"t": "input", "i": inp, "seq": self.seq})

    def pump(self):
        """非阻塞收快照（含分片重组），保留最新一帧。每帧调一次。"""
        self.sock.settimeout(0.0)
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except (BlockingIOError, socket.timeout):
                break
            except Exception:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            self.last_recv = time.time()   # 收到任意有效包都算主机存活
            t = msg.get("t")
            if t == "snap":
                self.snap = msg["s"]
            elif t == "frag":
                self._ingest_frag(msg)

    def _ingest_frag(self, frag):
        fid = frag.get("fid")
        total = frag.get("total")
        seq = frag.get("seq")
        if fid is None or total is None or seq is None:
            return
        grp = self._frags.get(fid)
        if grp is None:
            # 只保留最近两组，避免内存堆积
            if len(self._frags) > 2:
                old = min(self._frags.keys())
                del self._frags[old]
            grp = {"total": total, "have": set(), "parts": {}}
            self._frags[fid] = grp
        if grp["total"] != total:
            grp["total"] = total
            grp["have"] = set()
            grp["parts"] = {}
        try:
            chunk = base64.b64decode(frag.get("data", ""))
        except Exception:
            return
        grp["parts"][seq] = chunk
        grp["have"].add(seq)
        if len(grp["have"]) == total:
            # 全部到齐，按 seq 拼回完整 JSON
            buf = b"".join(grp["parts"][i] for i in range(total))
            try:
                obj = json.loads(buf.decode("utf-8"))
            except Exception:
                return
            if obj.get("t") == "snap":
                self.snap = obj["s"]
            del self._frags[fid]

    def leave(self):
        self._send({"t": "leave"})
