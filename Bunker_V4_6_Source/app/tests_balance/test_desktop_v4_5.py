"""Desktop integration contracts, without external network or firewall changes."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from server import app as api, network_utils as net

@pytest.fixture(autouse=True)
def connection_environment(monkeypatch):
    for k in ('BUNKER_CONNECTION_MODE','BUNKER_SHARE_HOST','BUNKER_SHARE_PORT','BUNKER_EXTERNAL_IP','BUNKER_EXTERNAL_LOOKUP','BUNKER_INSTANCE_ID'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(net, 'get_local_ip', lambda: '192.168.1.10')
    monkeypatch.setattr(net, '_cached_external_ip', None)
    def forbidden(*a, **kw):
        raise AssertionError('Desktop should not request an external IP service')
    monkeypatch.setattr(net.requests, 'get', forbidden)

@pytest.mark.parametrize('mode,host,port,expected', [
    ('porthole','',8008,'http://127.0.0.1:8008'),
    ('lan','192.168.1.22',8010,'http://192.168.1.22:8010'),
    ('lan','',8008,'http://192.168.1.10:8008'),
    ('vpn','25.22.33.44',8008,'http://25.22.33.44:8008'),
    ('public','203.0.113.5',9009,'http://203.0.113.5:9009'),
])
def test_selected_share_address(monkeypatch, mode, host, port, expected):
    monkeypatch.setenv('BUNKER_CONNECTION_MODE',mode)
    monkeypatch.setenv('BUNKER_SHARE_HOST',host)
    monkeypatch.setenv('BUNKER_SHARE_PORT',str(port))
    d=net.get_connection_info(8008)
    assert d['share_url']==expected
    assert d['host_url']=='http://127.0.0.1:8008'
    assert bool(d['qr_code']) == (mode != 'porthole')
    assert d['external_url'] == (expected if mode=='public' else None)

def test_no_automatic_external_lookup():
    assert net.get_external_ip(force_refresh=True) is None

def test_health_identity(monkeypatch):
    monkeypatch.setenv('BUNKER_INSTANCE_ID','identity-test')
    with TestClient(api.app) as c:
        d=c.get('/api/health').json()
    assert d['version']=='4.6.0' and d['instance']=='identity-test'

@pytest.mark.parametrize('mode', ['porthole','lan','vpn','public'])
def test_http_room_invite(monkeypatch,mode):
    monkeypatch.setenv('BUNKER_CONNECTION_MODE',mode)
    monkeypatch.setenv('BUNKER_SHARE_HOST', '25.22.33.44' if mode=='vpn' else '192.168.1.22')
    with TestClient(api.app) as c:
        info=c.get('/api/network-info').json()
        data=c.post('/api/room/create',json={'host_name':'Desktop test'}).json()
        assert data['share_url'].startswith(info['share_url']+'/?room=')
        assert bool(data['qr_code']) == (mode!='porthole')
        api.rooms.pop(data['room_code'],None)
        api.connections.pop(data['room_code'],None)

def test_in_game_help_is_offline():
    with TestClient(api.app) as c:
        r=c.get('/help')
        assert r.status_code==200
        assert all(x in r.text for x in ['Porthole','Hamachi','Белый','Погружение','Неизвестность'])
        assert c.get('/static/connection-help.css').status_code==200
        index=c.get('/').text
        assert 'href="/help"' in index and '? Помощь' in index

def test_porthole_keeps_guests_current_origin():
    s=(Path(api.STATIC_DIR)/'js/lobby.js').read_text()
    assert "connection_mode!=='porthole'" in s
    s=(Path(api.STATIC_DIR)/'js/app.js').read_text()
    assert "connection_mode === 'porthole'" in s
    assert 'if (!navigator.clipboard?.writeText)' in s
