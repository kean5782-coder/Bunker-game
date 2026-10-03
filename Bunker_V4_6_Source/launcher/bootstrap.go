package main

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const pythonVersion = "3.13.15"
const pythonURL = "https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip"

// Official Python release-page digest, verified 2026-09-20.
const pythonSHA = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"

type wheelFile struct {
	Filename string `json:"filename"`
	URL      string `json:"url"`
	Digests  struct {
		SHA string `json:"sha256"`
	} `json:"digests"`
	Yanked bool `json:"yanked"`
}

func chooseWheel(files []wheelFile) (wheelFile, error) {
	for _, suffix := range []string{"-cp313-cp313-win_amd64.whl", "-py3-none-any.whl", "-py2.py3-none-any.whl"} {
		for _, f := range files {
			if strings.HasSuffix(f.Filename, suffix) && !f.Yanked && len(f.Digests.SHA) == 64 {
				return f, nil
			}
		}
	}
	return wheelFile{}, errors.New("Совместимый Windows x64 wheel не найден")
}
func (m *Manager) runtimeReady() bool {
	if m.devPython != "" {
		_, e := os.Stat(m.devPython)
		return e == nil
	}
	p := filepath.Join(m.root, "runtime")
	b, e := os.ReadFile(filepath.Join(p, "READY.json"))
	if e != nil {
		return false
	}
	var marker map[string]string
	if json.Unmarshal(b, &marker) != nil || marker["version"] != Version || marker["python"] != pythonVersion {
		return false
	}
	_, e = os.Stat(filepath.Join(p, "python.exe"))
	return e == nil
}
func allowedDownload(raw string) bool {
	u, e := url.Parse(raw)
	if e != nil || u.Scheme != "https" || u.User != nil || u.Port() != "" {
		return false
	}
	switch strings.ToLower(u.Hostname()) {
	case "www.python.org", "pypi.org", "files.pythonhosted.org":
		return true
	}
	return false
}
func downloadClient() *http.Client {
	return &http.Client{Timeout: 150 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if len(via) > 5 || !allowedDownload(req.URL.String()) {
			return errors.New("Недопустимый адрес перенаправления")
		}
		return nil
	}}
}
func fetchBytes(ctx context.Context, raw string, limit int64) ([]byte, error) {
	if !allowedDownload(raw) {
		return nil, errors.New("Источник загрузки не разрешён")
	}
	req, e := http.NewRequestWithContext(ctx, "GET", raw, nil)
	if e != nil {
		return nil, e
	}
	req.Header.Set("User-Agent", "Bunker-Setup/"+Version)
	r, e := downloadClient().Do(req)
	if e != nil {
		return nil, e
	}
	defer r.Body.Close()
	if r.StatusCode != 200 {
		return nil, fmt.Errorf("Источник вернул HTTP %d", r.StatusCode)
	}
	b, e := io.ReadAll(io.LimitReader(r.Body, limit+1))
	if e != nil {
		return nil, e
	}
	if int64(len(b)) > limit {
		return nil, errors.New("Загрузка превышает допустимый размер")
	}
	return b, nil
}
func verifySHA(b []byte, want string) bool {
	sum := sha256.Sum256(b)
	return strings.EqualFold(hex.EncodeToString(sum[:]), want)
}
func (m *Manager) fetchCached(ctx context.Context, name, raw, digest string) ([]byte, error) {
	cache := filepath.Join(m.root, "downloads")
	os.MkdirAll(cache, 0700)
	p := filepath.Join(cache, filepath.Base(name))
	if b, e := os.ReadFile(p); e == nil && verifySHA(b, digest) {
		return b, nil
	}
	b, e := fetchBytes(ctx, raw, 100<<20)
	if e != nil {
		return nil, e
	}
	if !verifySHA(b, digest) {
		return nil, errors.New("Контрольная сумма не совпала. Файл не будет запущен.")
	}
	if e = os.WriteFile(p+".tmp", b, 0600); e != nil {
		return nil, e
	}
	os.Remove(p)
	if e = os.Rename(p+".tmp", p); e != nil {
		return nil, e
	}
	return b, nil
}
func (m *Manager) prepareRuntime(ctx context.Context) error {
	m.set("preparing", "Шаг 1/4: загрузка изолированного Python для Windows с python.org…")
	py, e := m.fetchCached(ctx, "python-"+pythonVersion+"-embed-amd64.zip", pythonURL, pythonSHA)
	if e != nil {
		return fmt.Errorf("Не удалось загрузить Python: %w. Нужен доступ к python.org; системный Python не изменён.", e)
	}
	stage := filepath.Join(m.root, "runtime.installing")
	os.RemoveAll(stage)
	if e = extractZIP(py, stage, false); e != nil {
		return e
	}
	vendor, _ := assets.ReadFile("vendor.zip")
	if e = extractZIP(vendor, filepath.Join(stage, "site-packages"), false); e != nil {
		return e
	}
	packages := [][2]string{{"pydantic_core", "2.46.4"}, {"pillow", "12.3.0"}, {"colorama", "0.4.6"}}
	for i, p := range packages {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		m.set("preparing", fmt.Sprintf("Шаг %d/4: загрузка Windows-компонента %s…", i+2, p[0]))
		b, e := fetchBytes(ctx, "https://pypi.org/pypi/"+p[0]+"/"+p[1]+"/json", 12<<20)
		if e != nil {
			return fmt.Errorf("Не удалось получить %s: %w", p[0], e)
		}
		var meta struct {
			URLs []wheelFile `json:"urls"`
		}
		if e = json.Unmarshal(b, &meta); e != nil {
			return e
		}
		wheel, e := chooseWheel(meta.URLs)
		if e != nil {
			return fmt.Errorf("%s: %w", p[0], e)
		}
		b, e = m.fetchCached(ctx, wheel.Filename, wheel.URL, wheel.Digests.SHA)
		if e != nil {
			return e
		}
		if e = extractZIP(b, filepath.Join(stage, "site-packages"), true); e != nil {
			return e
		}
	}
	if e = os.WriteFile(filepath.Join(stage, "python313._pth"), []byte("python313.zip\n.\nsite-packages\n../app\n"), 0600); e != nil {
		return e
	}
	m.set("preparing", "Проверка Python, библиотек и создания QR-кода…")
	testCtx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	cmd := exec.CommandContext(testCtx, filepath.Join(stage, "python.exe"), "-X", "utf8", "-c", "import fastapi,uvicorn,websockets,pydantic,requests,jinja2,multipart,qrcode,io; from PIL import Image; b=io.BytesIO(); qrcode.make('Bunker').save(b,format='PNG'); print('BUNKER_RUNTIME_OK')")
	prepareCommand(cmd)
	b, e := cmd.CombinedOutput()
	if e != nil || !strings.Contains(string(b), "BUNKER_RUNTIME_OK") {
		return fmt.Errorf("Windows-компоненты не прошли проверку: %v\n%s", e, string(b))
	}
	marker, _ := json.Marshal(map[string]string{"version": Version, "python": pythonVersion, "python_sha256": pythonSHA})
	if e = os.WriteFile(filepath.Join(stage, "READY.json"), marker, 0600); e != nil {
		return e
	}
	target := filepath.Join(m.root, "runtime")
	os.RemoveAll(target)
	if e = os.Rename(stage, target); e != nil {
		return e
	}
	m.mu.Lock()
	m.status.Ready = true
	m.mu.Unlock()
	return nil
}
func extractZIP(data []byte, root string, wheel bool) error {
	zr, e := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if e != nil {
		return e
	}
	abs, e := filepath.Abs(root)
	if e != nil {
		return e
	}
	if e = os.MkdirAll(abs, 0700); e != nil {
		return e
	}
	var total uint64
	for _, f := range zr.File {
		total += f.UncompressedSize64
		if total > 700<<20 {
			return errors.New("Распакованный архив слишком большой")
		}
		name := strings.ReplaceAll(f.Name, "\\", "/")
		if strings.HasPrefix(name, "/") || strings.Contains(name, ":") || strings.Contains(name, "\x00") || f.Mode()&os.ModeSymlink != 0 {
			return errors.New("Небезопасный путь внутри архива")
		}
		parts := strings.Split(name, "/")
		for _, p := range parts {
			if p == ".." {
				return errors.New("Выход за пределы папки архива запрещён")
			}
		}
		if wheel && len(parts) > 2 && strings.HasSuffix(parts[0], ".data") {
			if parts[1] == "purelib" || parts[1] == "platlib" {
				name = strings.Join(parts[2:], "/")
			} else {
				continue
			}
		}
		dest := filepath.Join(abs, filepath.FromSlash(name))
		rel, e := filepath.Rel(abs, dest)
		if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			return errors.New("Недопустимый путь ZIP")
		}
		if f.FileInfo().IsDir() {
			if e = os.MkdirAll(dest, 0700); e != nil {
				return e
			}
			continue
		}
		if e = os.MkdirAll(filepath.Dir(dest), 0700); e != nil {
			return e
		}
		in, e := f.Open()
		if e != nil {
			return e
		}
		out, e := os.OpenFile(dest, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
		if e != nil {
			in.Close()
			return e
		}
		_, e = io.Copy(out, in)
		in.Close()
		ec := out.Close()
		if e != nil {
			return e
		}
		if ec != nil {
			return ec
		}
	}
	return nil
}
