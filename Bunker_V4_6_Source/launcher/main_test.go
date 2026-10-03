package main

import (
	"archive/zip"
	"crypto/sha256"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestJoinURL(t *testing.T) {
	cases := []struct {
		addr       string
		port       int
		mode, want string
		ok         bool
	}{
		{"", 8008, "porthole", "http://127.0.0.1:8008/", true},
		{"192.168.1.20", 8008, "lan", "http://192.168.1.20:8008/", true},
		{"25.1.2.3:9001/?room=ABCD", 8008, "vpn", "http://25.1.2.3:9001/?room=ABCD", true},
		{"http://example.com:8008/?room=ABCD", 9000, "public", "http://example.com:8008/?room=ABCD", true},
		{"https://example.com/?room=ABCD", 9000, "public", "https://example.com/?room=ABCD", true},
		{"ABCD", 8008, "lan", "", false}, {"", 8008, "lan", "", false}, {"file:///etc/passwd", 8008, "lan", "", false}, {"http://user:pw@localhost:8008", 8008, "lan", "", false}, {"javascript:alert(1)", 8008, "lan", "", false}, {"127.0.0.1:99999", 8008, "lan", "", false},
	}
	for _, c := range cases {
		t.Run(c.addr+c.mode, func(t *testing.T) {
			got, e := joinURL(c.addr, c.port, c.mode)
			if (e == nil) != c.ok {
				t.Fatalf("%v", e)
			}
			if c.ok && got != c.want {
				t.Fatalf("got %s want %s", got, c.want)
			}
		})
	}
}
func TestSettings(t *testing.T) {
	s := Settings{Role: "host", Mode: "porthole", Port: 8008}
	if e := validateSettings(s); e != nil {
		t.Fatal(e)
	}
	for _, mode := range []string{"lan", "vpn", "public"} {
		s.Mode = mode
		s.Address = "127.0.0.1"
		if validateSettings(s) == nil {
			t.Fatal("loopback allowed")
		}
	}
	s.Mode = "public"
	s.ExternalPort = 8008
	for _, ip := range []string{"192.168.1.4", "10.0.0.4", "172.16.2.5", "100.64.0.8", "0.0.0.0", "224.0.0.1"} {
		s.Address = ip
		if validateSettings(s) == nil {
			t.Fatal(ip)
		}
	}
	s.Address = "8.8.8.8"
	if e := validateSettings(s); e != nil {
		t.Fatal(e)
	}
	s.Port = 80
	if validateSettings(s) == nil {
		t.Fatal("reserved port allowed")
	}
}
func TestZIPTraversal(t *testing.T) {
	for _, n := range []string{"../evil", "/absolute", "C:/evil", "a/../../evil", "a\\..\\evil"} {
		t.Run(n, func(t *testing.T) {
			if extractZIP(makeZIPForTest(map[string]string{n: "x"}), t.TempDir(), false) == nil {
				t.Fatalf("accepted %s", n)
			}
		})
	}
}
func TestZIPWheel(t *testing.T) {
	dir := t.TempDir()
	e := extractZIP(makeZIPForTest(map[string]string{"test.data/purelib/foo.py": "test", "test.data/scripts/skip.exe": "no", "normal/bar.py": "yes"}), dir, true)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = os.Stat(filepath.Join(dir, "foo.py")); e != nil {
		t.Fatal(e)
	}
	if _, e = os.Stat(filepath.Join(dir, "normal", "bar.py")); e != nil {
		t.Fatal(e)
	}
	if _, e = os.Stat(filepath.Join(dir, "test.data", "scripts", "skip.exe")); e == nil {
		t.Fatal("script extracted")
	}
}
func TestDownloadWhitelist(t *testing.T) {
	for _, s := range []string{"https://www.python.org/file", "https://pypi.org/pypi/a/json", "https://files.pythonhosted.org/test"} {
		if !allowedDownload(s) {
			t.Fatal(s)
		}
	}
	for _, s := range []string{"http://www.python.org/test", "https://www.python.org.attacker.com/test", "https://pypi.org:8008/file", "file:///foo", "https://user@pypi.org/file"} {
		if allowedDownload(s) {
			t.Fatal(s)
		}
	}
}
func TestSHA(t *testing.T) {
	b := []byte("hello")
	sha := fmt.Sprintf("%x", sha256.Sum256(b))
	if !verifySHA(b, sha) || verifySHA([]byte("evil"), sha) {
		t.Fatal("hash verification")
	}
}
func TestWheelSelection(t *testing.T) {
	makeFile := func(name string) wheelFile {
		f := wheelFile{Filename: name}
		f.Digests.SHA = strings.Repeat("a", 64)
		return f
	}
	f, e := chooseWheel([]wheelFile{makeFile("x-cp313-cp313-manylinux.whl"), makeFile("x-cp313-cp313-win_amd64.whl"), makeFile("x-cp313-cp313t-win_amd64.whl")})
	if e != nil || f.Filename != "x-cp313-cp313-win_amd64.whl" {
		t.Fatal(f, e)
	}
	if _, e := chooseWheel([]wheelFile{makeFile("x-cp312-cp312-win_amd64.whl")}); e == nil {
		t.Fatal("incompatible wheel chosen")
	}
}
func TestControlAccess(t *testing.T) {
	m := Manager{origin: "http://127.0.0.1:5555", token: "secret"}
	h := m.protect(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	cases := []struct {
		host, token, origin, path string
		code                      int
	}{{"127.0.0.1:5555", "secret", "http://127.0.0.1:5555", "/api/status", 200}, {"127.0.0.1:5555", "", "", "/api/status", 403}, {"evil.example:5555", "secret", "", "/api/status", 403}, {"127.0.0.1:5555", "secret", "https://evil.example", "/api/start", 403}, {"127.0.0.1:5555", "", "", "/", 200}}
	for _, c := range cases {
		r := httptest.NewRequest("GET", "http://"+c.host+c.path, nil)
		r.Header.Set("X-Bunker-Token", c.token)
		r.Header.Set("Origin", c.origin)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != c.code {
			t.Fatalf("%+v got %d", c, w.Code)
		}
	}
}
func TestGuestNeverStartsServer(t *testing.T) {
	m := Manager{root: t.TempDir(), status: Status{Phase: "idle"}}
	r := httptest.NewRequest("POST", "http://127.0.0.1/api/start", strings.NewReader(`{"role":"guest","mode":"porthole","port":8008,"address":""}`))
	w := httptest.NewRecorder()
	m.startHTTP(w, r)
	if w.Code != 200 || m.cmd != nil || m.status.Phase != "guest" {
		t.Fatalf("%d %+v", w.Code, m.status)
	}
	if _, e := os.Stat(filepath.Join(m.root, "runtime")); e == nil {
		t.Fatal("guest runtime created")
	}
}
func TestNoDownloadWithoutConsent(t *testing.T) {
	m := Manager{root: t.TempDir(), status: Status{Phase: "idle"}}
	r := httptest.NewRequest("POST", "http://localhost/api/start", strings.NewReader(`{"role":"host","mode":"porthole","port":8008,"allow_download":false}`))
	w := httptest.NewRecorder()
	m.startHTTP(w, r)
	if w.Code != 400 {
		t.Fatalf("got %d", w.Code)
	}
}
func TestReadyMarker(t *testing.T) {
	root := t.TempDir()
	m := Manager{root: root}
	if m.runtimeReady() {
		t.Fatal("unexpected ready")
	}
	os.MkdirAll(filepath.Join(root, "runtime"), 0700)
	os.WriteFile(filepath.Join(root, "runtime", "READY.json"), []byte(`{"version":"4.6.0","python":"3.13.15"}`), 0600)
	if m.runtimeReady() {
		t.Fatal("missing executable accepted")
	}
	os.WriteFile(filepath.Join(root, "runtime", "python.exe"), []byte("test"), 0600)
	if !m.runtimeReady() {
		t.Fatal("marker check failed")
	}
}
func TestRemoveEnv(t *testing.T) {
	v := removeEnv([]string{"Path=a", "PORT=80", "port=70", "OTHER=ok"}, "PORT")
	if len(v) != 2 || v[0] != "Path=a" {
		t.Fatal(v)
	}
}

func TestExportZIPExcludesPrivateData(t *testing.T) {
	root := t.TempDir()
	os.MkdirAll(filepath.Join(root, "runtime"), 0700)
	os.MkdirAll(filepath.Join(root, "logs"), 0700)
	os.WriteFile(filepath.Join(root, "runtime", "READY.json"), []byte(`{"version":"4.6.0","python":"3.13.15"}`), 0600)
	os.WriteFile(filepath.Join(root, "runtime", "python.exe"), []byte("TEST FIXTURE, NOT A RUNTIME"), 0600)
	os.WriteFile(filepath.Join(root, "settings.json"), []byte("private settings"), 0600)
	os.WriteFile(filepath.Join(root, "logs", "server.log"), []byte("private log"), 0600)
	m := Manager{root: root}
	if e := m.exportZIP(); e != nil {
		t.Fatal(e)
	}
	z, e := zip.OpenReader(filepath.Join(root, "exports", "Bunker_Portable_V4_6.zip"))
	if e != nil {
		t.Fatal(e)
	}
	defer z.Close()
	seen := map[string]bool{}
	for _, f := range z.File {
		seen[f.Name] = true
		if strings.Contains(f.Name, "settings") || strings.Contains(f.Name, "logs") {
			t.Fatal(f.Name)
		}
	}
	for _, n := range []string{"Bunker_Portable/Bunker.exe", "Bunker_Portable/BunkerData/runtime/python.exe", "Bunker_Portable/BunkerData/runtime/READY.json", "Bunker_Portable/START_HERE.txt"} {
		if !seen[n] {
			t.Fatal("missing", n)
		}
	}
}
