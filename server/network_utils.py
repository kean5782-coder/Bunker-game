import socket
import io
import base64
import os
import requests
import qrcode

_cached_external_ip = None

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
