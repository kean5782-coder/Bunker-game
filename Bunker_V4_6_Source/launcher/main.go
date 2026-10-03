package main

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

const Version = "4.6.0"

//go:embed ui/* payload.zip vendor.zip
var assets embed.FS

type Settings struct {
	Role          string `json:"role"`
	Mode          string `json:"mode"`
	Port          int    `json:"port"`
	Address       string `json:"address"`
	ExternalPort  int    `json:"external_port"`
	AllowDownload bool   `json:"allow_download"`
}
type Adapter struct {
	Name string `json:"name"`
	IP   string `json:"ip"`
}
type Status struct {
	Phase       string    `json:"phase"`
	Message     string    `json:"message"`
	Error       string    `json:"error"`
	GameURL     string    `json:"game_url"`
	ShareURL    string    `json:"share_url"`
	Ready       bool      `json:"runtime_ready"`
	ExportReady bool      `json:"export_ready"`
	Settings    Settings  `json:"settings"`
	Log         string    `json:"log"`
	DataDir     string    `json:"data_dir"`
	Adapters    []Adapter `json:"adapters"`
	Version     string    `json:"version"`
}
type Manager struct {
	mu                             sync.Mutex
	root, token, origin, devPython string
	status                         Status
	cmd                            *exec.Cmd
	processDone                    chan struct{}
	cancel                         context.CancelFunc
	job                            uintptr
	done                           chan struct{}
	closeOnce                      sync.Once
}

var app *Manager

func main() {
	noBrowser := flag.Bool("no-browser", false, "do not open browser (testing)")
	dataRoot := flag.String("data-root", "", "private data directory")
	devPython := flag.String("dev-python", "", "Linux test runtime only")
	flag.Parse()
	if runtime.GOOS == "windows" && *devPython != "" {
		fatalMessage("The test runtime option is not available in Windows builds.")
		return
	}
	root, err := selectRoot(*dataRoot)
	if err != nil {
		fatalMessage(err.Error())
		return
	}
	if err = os.MkdirAll(root, 0700); err != nil {
		fatalMessage("Не удалось создать папку данных: " + err.Error())
		return
	}
	if old, ok := existingInstance(root); ok {
		if !*noBrowser {
			openTarget(old)
		}
		fmt.Println(old)
		return
	}
	lock := filepath.Join(root, "launcher.lock")
	f, err := os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		time.Sleep(time.Second)
		if old, ok := existingInstance(root); ok {
			if !*noBrowser {
				openTarget(old)
			}
			return
		}
		os.Remove(lock)
		f, err = os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	}
	if err != nil {
		fatalMessage("Помощник уже запускается. Откройте его из значка в области уведомлений.")
		return
	}
	f.Close()
	defer os.Remove(lock)
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		fatalMessage(err.Error())
		return
	}
	tokenBytes := make([]byte, 32)
	if _, err = rand.Read(tokenBytes); err != nil {
		fatalMessage(err.Error())
		return
	}
	app = &Manager{root: root, token: hex.EncodeToString(tokenBytes), origin: "http://" + ln.Addr().String(), devPython: *devPython, done: make(chan struct{})}
	app.status = Status{Phase: "idle", Message: "Выберите вашу роль и способ подключения.", Settings: Settings{Role: "host", Mode: "porthole", Port: 8008, ExternalPort: 8008}, DataDir: root, Version: Version}
	if b, e := os.ReadFile(filepath.Join(root, "settings.json")); e == nil {
		var s Settings
		if json.Unmarshal(b, &s) == nil && validateSettings(s) == nil {
			s.AllowDownload = false
			app.status.Settings = s
		}
	}
	app.status.Ready = app.runtimeReady()
	app.status.Adapters = listAdapters()
	href := app.origin + "/#token=" + app.token
	record, _ := json.Marshal(map[string]string{"url": href, "token": app.token, "origin": app.origin})
	os.WriteFile(filepath.Join(root, "instance.json"), record, 0600)
	defer os.Remove(filepath.Join(root, "instance.json"))
	mux := http.NewServeMux()
	ui, _ := fs.Sub(assets, "ui")
	mux.Handle("/", http.FileServer(http.FS(ui)))
	mux.HandleFunc("/api/status", app.statusHTTP)
	mux.HandleFunc("/api/start", app.startHTTP)
	mux.HandleFunc("/api/stop", app.stopHTTP)
	mux.HandleFunc("/api/exit", app.exitHTTP)
	mux.HandleFunc("/api/check", app.checkHTTP)
	mux.HandleFunc("/api/export", app.exportHTTP)
	mux.HandleFunc("/api/export-file", app.exportFileHTTP)
	mux.HandleFunc("/api/logs", app.logsHTTP)
	srv := &http.Server{Handler: app.protect(mux), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192}
	go srv.Serve(ln)
	fmt.Println(href)
	if !*noBrowser {
		if e := openTarget(href); e != nil {
			fatalMessage("Откройте помощник в браузере:\n" + href)
		}
	}
	startTray(href, app.shutdown, *noBrowser)
	<-app.done
	srv.Close()
	app.stopGame()
}

func selectRoot(override string) (string, error) {
	if override != "" {
		return filepath.Abs(override)
	}
	exe, e := os.Executable()
	if e != nil {
		return "", e
	}
	portable := filepath.Join(filepath.Dir(exe), "BunkerData")
	if _, e = os.Stat(filepath.Join(portable, "runtime", "READY.json")); e == nil {
		return portable, nil
	}
	base, e := os.UserCacheDir()
	if e != nil {
		return "", e
	}
	return filepath.Join(base, "Bunker", Version), nil
}
func existingInstance(root string) (string, bool) {
	b, e := os.ReadFile(filepath.Join(root, "instance.json"))
	if e != nil {
		return "", false
	}
	var d map[string]string
	if json.Unmarshal(b, &d) != nil {
		return "", false
	}
	u, e := url.Parse(d["origin"])
	if e != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" {
		return "", false
	}
	req, _ := http.NewRequest("GET", d["origin"]+"/api/status", nil)
	req.Header.Set("X-Bunker-Token", d["token"])
	c := http.Client{Timeout: 700 * time.Millisecond}
	r, e := c.Do(req)
	if e != nil {
		return "", false
	}
	defer r.Body.Close()
	var s Status
	if r.StatusCode != 200 || json.NewDecoder(r.Body).Decode(&s) != nil || s.Version != Version {
		return "", false
	}
	return d["url"], true
}
func (m *Manager) protect(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != strings.TrimPrefix(m.origin, "http://") {
			http.Error(w, "Invalid host", 403)
			return
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
		if strings.HasPrefix(r.URL.Path, "/api/") {
			t := r.Header.Get("X-Bunker-Token")
			if subtle.ConstantTimeCompare([]byte(t), []byte(m.token)) != 1 {
				http.Error(w, "Access denied", 403)
				return
			}
			if o := r.Header.Get("Origin"); o != "" && o != m.origin {
				http.Error(w, "Invalid origin", 403)
				return
			}
			r.Body = http.MaxBytesReader(w, r.Body, 65536)
		}
		next.ServeHTTP(w, r)
	})
}
func reply(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}
func needPost(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != "POST" {
		http.Error(w, "POST required", 405)
		return false
	}
	return true
}
func (m *Manager) snapshot() Status {
	m.mu.Lock()
	s := m.status
	m.mu.Unlock()
	s.Log = tailFile(filepath.Join(m.root, "logs", "server.log"), 12000)
	return s
}
func (m *Manager) statusHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "GET required", 405)
		return
	}
	reply(w, 200, m.snapshot())
}
func (m *Manager) set(phase, msg string) {
	m.mu.Lock()
	m.status.Phase = phase
	m.status.Message = msg
	m.mu.Unlock()
}
func (m *Manager) fail(err error) {
	m.mu.Lock()
	m.status.Phase = "error"
	m.status.Error = err.Error()
	m.status.Message = "Действие не выполнено. Проверьте сообщение ниже."
	m.mu.Unlock()
}
func listAdapters() []Adapter {
	out := []Adapter{}
	ifs, _ := net.Interfaces()
	for _, n := range ifs {
		if n.Flags&net.FlagUp == 0 || n.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, _ := n.Addrs()
		for _, a := range addrs {
			ip, _, e := net.ParseCIDR(a.String())
			if e == nil && ip.To4() != nil && !ip.IsLoopback() {
				out = append(out, Adapter{n.Name, ip.String()})
			}
		}
	}
	return out
}
func validPort(p int) bool { return p >= 1024 && p <= 65535 }
func validateSettings(s Settings) error {
	if s.Role != "host" && s.Role != "guest" {
		return errors.New("Выберите роль")
	}
	if !validPort(s.Port) {
		return errors.New("Порт должен быть от 1024 до 65535")
	}
	switch s.Mode {
	case "lan", "porthole", "vpn", "public":
	default:
		return errors.New("Выберите способ подключения")
	}
	if s.Role == "guest" {
		_, e := joinURL(s.Address, s.Port, s.Mode)
		return e
	}
	if s.Mode != "porthole" {
		ip := net.ParseIP(strings.TrimSpace(s.Address))
		if ip == nil || ip.To4() == nil || ip.IsUnspecified() || ip.IsLoopback() || !ip.IsGlobalUnicast() {
			return errors.New("Укажите IPv4-адрес выбранного адаптера или белый IPv4, не 127.0.0.1 и не 0.0.0.0")
		}
		if s.Mode == "public" {
			_, cgnat, _ := net.ParseCIDR("100.64.0.0/10")
			if ip.IsPrivate() || cgnat.Contains(ip) {
				return errors.New("Этот адрес частный или CGNAT, а не белый IP. Выберите Porthole или VPN.")
			}
			if !validPort(s.ExternalPort) {
				return errors.New("Укажите внешний TCP-порт от 1024 до 65535")
			}
		}
	}
	return nil
}
func joinURL(address string, port int, mode string) (string, error) {
	address = strings.TrimSpace(address)
	if address == "" && mode == "porthole" {
		address = "127.0.0.1"
	}
	if address == "" {
		return "", errors.New("Введите адрес сервера ведущего")
	}
	hadScheme := strings.Contains(address, "://")
	if !hadScheme {
		address = "http://" + address
	}
	u, e := url.Parse(address)
	if e != nil || u.Hostname() == "" || u.User != nil || (u.Scheme != "http" && u.Scheme != "https") || strings.ContainsAny(u.Hostname(), "\"<> \\\r\n") {
		return "", errors.New("Нужен IP или ссылка http://адрес:порт, не код комнаты")
	}
	if !strings.Contains(u.Hostname(), ".") && u.Hostname() != "localhost" && net.ParseIP(u.Hostname()) == nil {
		return "", errors.New("Введите адрес сервера, а не код комнаты")
	}
	if u.Port() == "" && !hadScheme {
		u.Host = net.JoinHostPort(u.Hostname(), strconv.Itoa(port))
	}
	if p := u.Port(); p != "" {
		n, e := strconv.Atoi(p)
		if e != nil || n < 1 || n > 65535 {
			return "", errors.New("Неверный порт в ссылке")
		}
	}
	u.Fragment = ""
	if u.Path == "" {
		u.Path = "/"
	}
	return u.String(), nil
}
func (m *Manager) startHTTP(w http.ResponseWriter, r *http.Request) {
	if !needPost(w, r) {
		return
	}
	var s Settings
	if json.NewDecoder(r.Body).Decode(&s) != nil {
		reply(w, 400, map[string]string{"error": "Неверные настройки"})
		return
	}
	if e := validateSettings(s); e != nil {
		reply(w, 400, map[string]string{"error": e.Error()})
		return
	}
	m.mu.Lock()
	if m.status.Phase == "preparing" || m.status.Phase == "starting" || m.status.Phase == "exporting" || m.cmd != nil {
		m.mu.Unlock()
		reply(w, 409, map[string]string{"error": "Сначала остановите уже запущенный сервер или дождитесь завершения подготовки."})
		return
	}
	m.status.Error = ""
	m.status.Settings = s
	m.status.ExportReady = false
	if s.Role == "guest" {
		m.status.Phase = "guest"
		m.status.Message = "Сервер на вашем компьютере не запускается."
		u, _ := joinURL(s.Address, s.Port, s.Mode)
		m.status.GameURL = u
		m.status.ShareURL = ""
		m.mu.Unlock()
		reply(w, 200, map[string]string{"url": u})
		return
	}
	if !m.runtimeReady() && !s.AllowDownload {
		m.mu.Unlock()
		reply(w, 400, map[string]string{"error": "Первый запуск ведущего требует загрузки Windows-компонентов. Подтвердите её в помощнике."})
		return
	}
	m.status.Phase = "preparing"
	m.status.Message = "Проверка файлов игры…"
	m.status.GameURL = ""
	m.status.ShareURL = ""
	ctx, cancel := context.WithCancel(context.Background())
	m.cancel = cancel
	m.mu.Unlock()
	b, _ := json.Marshal(s)
	os.WriteFile(filepath.Join(m.root, "settings.json"), b, 0600)
	go m.startGame(ctx, s)
	reply(w, 202, map[string]bool{"ok": true})
}
func (m *Manager) startGame(ctx context.Context, s Settings) {
	payload, _ := assets.ReadFile("payload.zip")
	if e := extractZIP(payload, filepath.Join(m.root, "app"), false); e != nil {
		m.fail(e)
		return
	}
	if !m.runtimeReady() {
		if e := m.prepareRuntime(ctx); e != nil {
			m.fail(e)
			return
		}
	}
	if ctx.Err() != nil {
		m.fail(errors.New("Подготовка отменена"))
		return
	}
	bind := "0.0.0.0"
	if s.Mode == "porthole" {
		bind = "127.0.0.1"
	}
	l, e := net.Listen("tcp4", net.JoinHostPort(bind, strconv.Itoa(s.Port)))
	if e != nil {
		m.fail(fmt.Errorf("Порт %d занят или недоступен. Чужие программы не остановлены. Закройте старый сервер или выберите другой порт. %v", s.Port, e))
		return
	}
	l.Close()
	m.set("starting", "Запускается игровой сервер…")
	os.MkdirAll(filepath.Join(m.root, "logs"), 0700)
	logPath := filepath.Join(m.root, "logs", "server.log")
	os.Rename(logPath, logPath+".previous")
	logFile, e := os.OpenFile(logPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if e != nil {
		m.fail(e)
		return
	}
	python := filepath.Join(m.root, "runtime", "python.exe")
	if m.devPython != "" {
		python = m.devPython
	}
	cmd := exec.Command(python, "-X", "utf8", filepath.Join(m.root, "app", "desktop_server.py"))
	cmd.Dir = filepath.Join(m.root, "app")
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	prepareCommand(cmd)
	inst := make([]byte, 16)
	rand.Read(inst)
	instance := hex.EncodeToString(inst)
	env := os.Environ()
	for _, key := range []string{"PORT", "BUNKER_CONNECTION_MODE", "BUNKER_SHARE_HOST", "BUNKER_SHARE_PORT", "BUNKER_INSTANCE_ID", "BUNKER_EXTERNAL_LOOKUP", "BUNKER_MANAGE_FIREWALL", "BUNKER_DOMAIN", "BUNKER_EXTERNAL_IP", "PYTHONPATH", "PYTHONHOME"} {
		env = removeEnv(env, key)
	}
	sharePort := s.Port
	if s.Mode == "public" {
		sharePort = s.ExternalPort
	}
	env = append(env, "PORT="+strconv.Itoa(s.Port), "BUNKER_CONNECTION_MODE="+s.Mode, "BUNKER_SHARE_HOST="+s.Address, "BUNKER_SHARE_PORT="+strconv.Itoa(sharePort), "BUNKER_INSTANCE_ID="+instance, "BUNKER_MANAGE_FIREWALL=0", "BUNKER_EXTERNAL_LOOKUP=0")
	cmd.Env = env
	if e = cmd.Start(); e != nil {
		logFile.Close()
		m.fail(fmt.Errorf("Не удалось запустить сервер: %w", e))
		return
	}
	finished := make(chan struct{})
	m.mu.Lock()
	m.cmd = cmd
	m.processDone = finished
	m.job = attachJob(cmd)
	m.status.Ready = true
	m.mu.Unlock()
	go func() {
		e := cmd.Wait()
		logFile.Close()
		m.mu.Lock()
		if m.cmd == cmd {
			m.cmd = nil
			closeJob(m.job)
			m.job = 0
			if m.status.Phase == "running" || m.status.Phase == "starting" {
				m.status.Phase = "error"
				m.status.Error = fmt.Sprintf("Сервер завершился: %v. Откройте журнал.", e)
			}
		}
		m.mu.Unlock()
		close(finished)
	}()
	gameURL := fmt.Sprintf("http://127.0.0.1:%d", s.Port)
	c := http.Client{Timeout: 500 * time.Millisecond}
	for i := 0; i < 160; i++ {
		select {
		case <-ctx.Done():
			m.stopGame()
			return
		case <-finished:
			m.fail(errors.New("Сервер не запустился. Откройте журнал ниже."))
			return
		default:
		}
		resp, e := c.Get(gameURL + "/api/health")
		if e == nil {
			var health map[string]any
			e = json.NewDecoder(resp.Body).Decode(&health)
			resp.Body.Close()
			if e == nil && health["instance"] == instance {
				host := s.Address
				if s.Mode == "porthole" {
					host = "127.0.0.1"
				}
				m.mu.Lock()
				m.status.Phase = "running"
				m.status.Message = "Сервер работает. Откройте игру и создайте комнату."
				m.status.GameURL = gameURL
				m.status.ShareURL = fmt.Sprintf("http://%s:%d", host, sharePort)
				m.mu.Unlock()
				return
			}
		}
		time.Sleep(250 * time.Millisecond)
	}
	m.stopGame()
	m.fail(errors.New("Сервер не подтвердил готовность. Посмотрите журнал и проверьте защиту Windows."))
}
func removeEnv(env []string, key string) []string {
	out := []string{}
	for _, v := range env {
		if !strings.EqualFold(strings.SplitN(v, "=", 2)[0], key) {
			out = append(out, v)
		}
	}
	return out
}
func (m *Manager) stopGame() {
	m.mu.Lock()
	cancel := m.cancel
	m.cancel = nil
	cmd := m.cmd
	m.cmd = nil
	finished := m.processDone
	m.processDone = nil
	job := m.job
	m.job = 0
	m.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	if cmd != nil && cmd.Process != nil {
		cmd.Process.Kill()
	}
	closeJob(job)
	// Wait for the owned process to release its sockets before reporting "stopped".
	if finished != nil {
		select {
		case <-finished:
		case <-time.After(5 * time.Second):
		}
	}
}
func (m *Manager) stopHTTP(w http.ResponseWriter, r *http.Request) {
	if !needPost(w, r) {
		return
	}
	m.mu.Lock()
	phase := m.status.Phase
	m.mu.Unlock()
	if phase == "preparing" || phase == "exporting" {
		reply(w, 409, map[string]string{"error": "Во время подготовки дождитесь завершения или закройте помощник кнопкой «Завершить»."})
		return
	}
	m.stopGame()
	m.set("idle", "Сервер остановлен. Партия в памяти сервера завершена.")
	reply(w, 200, map[string]bool{"ok": true})
}
func (m *Manager) shutdown() { m.closeOnce.Do(func() { close(m.done) }) }
func (m *Manager) exitHTTP(w http.ResponseWriter, r *http.Request) {
	if !needPost(w, r) {
		return
	}
	reply(w, 200, map[string]bool{"ok": true})
	go func() { time.Sleep(200 * time.Millisecond); m.shutdown() }()
}
func (m *Manager) checkHTTP(w http.ResponseWriter, r *http.Request) {
	if !needPost(w, r) {
		return
	}
	var s Settings
	if json.NewDecoder(r.Body).Decode(&s) != nil {
		reply(w, 400, map[string]string{"error": "Неверный адрес"})
		return
	}
	u, e := joinURL(s.Address, s.Port, s.Mode)
	if e != nil {
		reply(w, 400, map[string]string{"error": e.Error()})
		return
	}
	parsed, _ := url.Parse(u)
	parsed.Path = "/api/health"
	parsed.RawQuery = ""
	c := http.Client{Timeout: 4 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
	resp, e := c.Get(parsed.String())
	if e != nil {
		reply(w, 200, map[string]any{"ok": false, "message": "Сервер не ответил. Проверьте адрес, запущен ли сервер, VPN/Porthole и брандмауэр."})
		return
	}
	defer resp.Body.Close()
	var d map[string]any
	ok := json.NewDecoder(io.LimitReader(resp.Body, 65536)).Decode(&d) == nil && d["application"] == "bunker"
	message := "Адрес ответил, но это не сервер Бункера V4.6. Возможно, здесь запущена старая версия."
	if ok {
		message = "Сервер Бункера доступен с этого компьютера. WebSocket и внешнее подключение этим тестом не проверяются."
	}
	reply(w, 200, map[string]any{"ok": ok, "message": message})
}
func tailFile(path string, limit int) string {
	f, e := os.Open(path)
	if e != nil {
		return ""
	}
	defer f.Close()
	st, e := f.Stat()
	if e != nil {
		return ""
	}
	if st.Size() > int64(limit) {
		f.Seek(-int64(limit), io.SeekEnd)
	}
	b, _ := io.ReadAll(io.LimitReader(f, int64(limit)))
	return strings.ToValidUTF8(string(b), "?")
}
func (m *Manager) logsHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Content-Disposition", "attachment; filename=bunker-server.log")
	io.WriteString(w, tailFile(filepath.Join(m.root, "logs", "server.log"), 2<<20))
}
func (m *Manager) exportHTTP(w http.ResponseWriter, r *http.Request) {
	if !needPost(w, r) {
		return
	}
	m.mu.Lock()
	if !m.status.Ready || m.status.Phase == "preparing" || m.status.Phase == "exporting" || m.status.Phase == "starting" {
		m.mu.Unlock()
		reply(w, 400, map[string]string{"error": "Сначала успешно подготовьте и запустите игру"})
		return
	}
	oldPhase := m.status.Phase
	m.status.Phase = "exporting"
	m.status.Message = "Создаётся автономный ZIP без журналов и личных настроек…"
	m.mu.Unlock()
	go func() {
		e := m.exportZIP()
		if e != nil {
			m.fail(e)
			return
		}
		m.mu.Lock()
		m.status.ExportReady = true
		m.status.Phase = oldPhase
		m.status.Message = "Автономный ZIP готов. Передайте его на другой Windows-компьютер."
		m.mu.Unlock()
	}()
	reply(w, 202, map[string]bool{"ok": true})
}
func (m *Manager) exportZIP() error {
	if !m.runtimeReady() || m.devPython != "" {
		return errors.New("Автономный пакет создаётся только после подготовки Windows-компонентов")
	}
	os.MkdirAll(filepath.Join(m.root, "exports"), 0700)
	path := filepath.Join(m.root, "exports", "Bunker_Portable_V4_6.zip")
	f, e := os.Create(path + ".tmp")
	if e != nil {
		return e
	}
	z := zip.NewWriter(f)
	add := func(src, name string) error {
		in, e := os.Open(src)
		if e != nil {
			return e
		}
		defer in.Close()
		w, e := z.Create(name)
		if e != nil {
			return e
		}
		_, e = io.Copy(w, in)
		return e
	}
	exe, _ := os.Executable()
	e = add(exe, "Bunker_Portable/Bunker.exe")
	if e == nil {
		e = filepath.WalkDir(filepath.Join(m.root, "runtime"), func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				return nil
			}
			if d.Type()&os.ModeSymlink != 0 {
				return errors.New("Ссылки в runtime запрещены")
			}
			rel, _ := filepath.Rel(filepath.Join(m.root, "runtime"), p)
			return add(p, "Bunker_Portable/BunkerData/runtime/"+filepath.ToSlash(rel))
		})
	}
	if e == nil {
		w, _ := z.Create("Bunker_Portable/START_HERE.txt")
		io.WriteString(w, "Распакуйте всю папку. Запустите Bunker.exe. Компоненты уже включены. Помощник и инструкция откроются в браузере. Не удаляйте BunkerData.\r\n")
	}
	ez := z.Close()
	ef := f.Close()
	if e == nil {
		e = ez
	}
	if e == nil {
		e = ef
	}
	if e != nil {
		os.Remove(path + ".tmp")
		return e
	}
	os.Remove(path)
	return os.Rename(path+".tmp", path)
}
func (m *Manager) exportFileHTTP(w http.ResponseWriter, r *http.Request) {
	m.mu.Lock()
	ok := m.status.ExportReady
	m.mu.Unlock()
	if !ok {
		http.Error(w, "ZIP not ready", 404)
		return
	}
	w.Header().Set("Content-Disposition", "attachment; filename=Bunker_Portable_V4_6.zip")
	http.ServeFile(w, r, filepath.Join(m.root, "exports", "Bunker_Portable_V4_6.zip"))
}

// Referenced by ZIP safety tests.
func makeZIPForTest(files map[string]string) []byte {
	var b bytes.Buffer
	z := zip.NewWriter(&b)
	for n, s := range files {
		w, _ := z.Create(n)
		io.WriteString(w, s)
	}
	z.Close()
	return b.Bytes()
}
