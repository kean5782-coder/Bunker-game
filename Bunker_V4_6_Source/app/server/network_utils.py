import socket
import io
import base64
import os
import requests
import qrcode

import json

_cached_external_ip = None
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))

def get_config() -> dict:
    """Loads configuration from config.json or returns defaults"""
    defaults = {"port": 8008, "domain": ""}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults

def get_domain_info():
    """Returns (display_domain, punycode_domain) or (None, None)"""
    env_domain = os.getenv("BUNKER_DOMAIN")
    domain = env_domain or get_config().get("domain")
    if not domain or not domain.strip():
        return None, None
    
    clean_domain = domain.strip().lower().replace("http://", "").replace("https://", "").rstrip("/")
    try:
        punycode = clean_domain.encode("idna").decode("ascii")
    except Exception:
        punycode = clean_domain
    return clean_domain, punycode

def get_local_ip():
    """Returns local network IP address (e.g. 192.168.1.50)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't need to be reachable, just triggers route lookup
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def get_external_ip(force_refresh=False):
    """Returns external public IP address using public services with timeout"""
    global _cached_external_ip
    if _cached_external_ip and not force_refresh:
        return _cached_external_ip

    # Check environment variable first if user specified manually
    env_ip = os.getenv("BUNKER_EXTERNAL_IP")
    if env_ip:
        _cached_external_ip = env_ip.strip()
        return _cached_external_ip

    # V4.5: no external lookup without an explicit user request.
    if os.getenv("BUNKER_EXTERNAL_LOOKUP", "0") != "1":
        return None

    services = [
        ("https://api.ipify.org?format=text", 2.5),
        ("https://icanhazip.com", 2.5),
        ("https://ifconfig.me/ip", 2.5)
    ]
    for url, timeout in services:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip and len(ip.split('.')) == 4:
                    _cached_external_ip = ip
                    return ip
        except Exception:
            continue

    return None

def generate_qr_data_url(url: str) -> str:
    """Generates a base64 encoded PNG data URL for the given URL"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00ffcc", back_color="#0f141d")
    buffer = io.BytesIO()
    img.save(buffer)
    b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return f"data:image/png;base64,{b64_str}"


def get_connection_info(port: int) -> dict:
    """Addresses selected by the desktop assistant; never probe external services."""
    mode = os.getenv("BUNKER_CONNECTION_MODE", "lan")
    if mode not in {"lan", "porthole", "vpn", "public"}:
        mode = "lan"
    local_ip = get_local_ip()
    selected = os.getenv("BUNKER_SHARE_HOST", "").strip()
    if mode == "porthole":
        share_host = "127.0.0.1"
    else:
        share_host = selected or (local_ip if mode == "lan" else "")
    share_port = int(os.getenv("BUNKER_SHARE_PORT", str(port)))
    base = f"http://{share_host}:{share_port}" if share_host else None
    labels = {"lan": "Локальная сеть", "porthole": "Porthole",
              "vpn": "Hamachi / Radmin / VPN", "public": "Белый IP"}
    note = ("Сначала подключитесь к ведущему в Porthole и подтвердите TCP-порт. "
            "Если локальный порт отличается, замените его в ссылке. Код Porthole и код комнаты Бункера различаются."
            if mode == "porthole" else
            "Откройте ссылку на компьютере, имеющем доступ к сети ведущего.")
    return {"port": port, "connection_mode": mode, "connection_label": labels[mode],
            "local_ip": local_ip, "local_url": f"http://{local_ip}:{port}",
            "host_url": f"http://127.0.0.1:{port}", "share_url": base,
            "external_url": base if mode == "public" else None,
            "external_ip": selected if mode == "public" else None,
            "display_url": base, "share_note": note, "domain": None, "domain_punycode": None,
            "qr_code": generate_qr_data_url(base) if base and mode != "porthole" else None}
