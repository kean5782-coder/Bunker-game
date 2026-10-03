package main

import (
	"fmt"
	"os/exec"
	"runtime"
	"syscall"
	"unsafe"
)

var user32 = syscall.NewLazyDLL("user32.dll")
var shell32 = syscall.NewLazyDLL("shell32.dll")
var kernel32 = syscall.NewLazyDLL("kernel32.dll")

func wide(s string) *uint16 { p, _ := syscall.UTF16PtrFromString(s); return p }
func openTarget(target string) error {
	v, _, e := shell32.NewProc("ShellExecuteW").Call(0, uintptr(unsafe.Pointer(wide("open"))), uintptr(unsafe.Pointer(wide(target))), 0, 0, 1)
	if v <= 32 {
		return fmt.Errorf("ShellExecute: %v", e)
	}
	return nil
}
func fatalMessage(s string) {
	user32.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(wide(s))), uintptr(unsafe.Pointer(wide("Бункер"))), 0x10)
}
func prepareCommand(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
}

type jobBasic struct {
	Time1, Time2         int64
	Flags                uint32
	_                    uint32
	Min, Max             uintptr
	Active               uint32
	_                    uint32
	Affinity             uintptr
	Priority, Scheduling uint32
}
type ioCounters struct{ R1, R2, R3, R4, R5, R6 uint64 }
type jobInfo struct {
	Basic                                          jobBasic
	IO                                             ioCounters
	ProcessMemory, JobMemory, PeakProcess, PeakJob uintptr
}

func attachJob(cmd *exec.Cmd) uintptr {
	h, _, _ := kernel32.NewProc("CreateJobObjectW").Call(0, 0)
	if h == 0 {
		return 0
	}
	info := jobInfo{}
	info.Basic.Flags = 0x2000
	r, _, _ := kernel32.NewProc("SetInformationJobObject").Call(h, 9, uintptr(unsafe.Pointer(&info)), unsafe.Sizeof(info))
	if r == 0 {
		closeJob(h)
		return 0
	}
	ph, _, _ := kernel32.NewProc("OpenProcess").Call(0x0001|0x0100, 0, uintptr(cmd.Process.Pid))
	if ph == 0 {
		closeJob(h)
		return 0
	}
	r, _, _ = kernel32.NewProc("AssignProcessToJobObject").Call(h, ph)
	kernel32.NewProc("CloseHandle").Call(ph)
	if r == 0 {
		closeJob(h)
		return 0
	}
	return h
}
func closeJob(h uintptr) {
	if h != 0 {
		kernel32.NewProc("CloseHandle").Call(h)
	}
}

type wndclass struct {
	Size, Style                        uint32
	Proc                               uintptr
	ClsExtra, WndExtra                 int32
	Instance, Icon, Cursor, Background uintptr
	Menu, Class                        *uint16
	SmallIcon                          uintptr
}
type point struct{ X, Y int32 }
type msg struct {
	Wnd            uintptr
	Message        uint32
	WParam, LParam uintptr
	Time           uint32
	Pt             point
	Private        uint32
}
type notifyData struct {
	Size                uint32
	Wnd                 uintptr
	ID, Flags, Callback uint32
	Icon                uintptr
	Tip                 [128]uint16
	State, StateMask    uint32
	Info                [256]uint16
	Timeout             uint32
	InfoTitle           [64]uint16
	InfoFlags           uint32
	GUID                [16]byte
	Balloon             uintptr
}

var trayData notifyData

func startTray(url string, stop func(), disabled bool) {
	if disabled {
		return
	}
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		inst, _, _ := kernel32.NewProc("GetModuleHandleW").Call(0)
		icon, _, _ := user32.NewProc("LoadIconW").Call(0, 32512)
		callback := syscall.NewCallback(func(hwnd uintptr, message uint32, wp, lp uintptr) uintptr {
			if message == 0x8001 {
				if lp == 0x0203 {
					openTarget(url)
				}
				if lp == 0x0205 {
					menu, _, _ := user32.NewProc("CreatePopupMenu").Call()
					user32.NewProc("AppendMenuW").Call(menu, 0, 1, uintptr(unsafe.Pointer(wide("Открыть помощник"))))
					user32.NewProc("AppendMenuW").Call(menu, 0, 2, uintptr(unsafe.Pointer(wide("Завершить Бункер"))))
					var pt point
					user32.NewProc("GetCursorPos").Call(uintptr(unsafe.Pointer(&pt)))
					user32.NewProc("SetForegroundWindow").Call(hwnd)
					chosen, _, _ := user32.NewProc("TrackPopupMenu").Call(menu, 0x0100|0x0002, uintptr(pt.X), uintptr(pt.Y), 0, hwnd, 0)
					user32.NewProc("DestroyMenu").Call(menu)
					if chosen == 1 {
						openTarget(url)
					}
					if chosen == 2 {
						r, _, _ := user32.NewProc("MessageBoxW").Call(hwnd, uintptr(unsafe.Pointer(wide("Завершить Бункер? Если вы ведущий, сервер остановится и текущая партия будет потеряна."))), uintptr(unsafe.Pointer(wide("Завершение игры"))), 0x24)
						if r == 6 {
							shell32.NewProc("Shell_NotifyIconW").Call(2, uintptr(unsafe.Pointer(&trayData)))
							stop()
						}
					}
				}
				return 0
			}
			r, _, _ := user32.NewProc("DefWindowProcW").Call(hwnd, uintptr(message), wp, lp)
			return r
		})
		name := wide("BunkerDesktop45")
		wc := wndclass{Proc: callback, Instance: inst, Class: name}
		wc.Size = uint32(unsafe.Sizeof(wc))
		user32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&wc)))
		hwnd, _, _ := user32.NewProc("CreateWindowExW").Call(0, uintptr(unsafe.Pointer(name)), uintptr(unsafe.Pointer(name)), 0, 0, 0, 0, 0, 0, 0, inst, 0)
		if hwnd == 0 {
			return
		}
		trayData = notifyData{Wnd: hwnd, ID: 1, Flags: 1 | 2 | 4, Callback: 0x8001, Icon: icon}
		trayData.Size = uint32(unsafe.Sizeof(trayData))
		tip, _ := syscall.UTF16FromString("Бункер — помощник подключения")
		copy(trayData.Tip[:], tip)
		shell32.NewProc("Shell_NotifyIconW").Call(0, uintptr(unsafe.Pointer(&trayData)))
		var message msg
		for {
			r, _, _ := user32.NewProc("GetMessageW").Call(uintptr(unsafe.Pointer(&message)), 0, 0, 0)
			if r == 0 || r == ^uintptr(0) {
				break
			}
			user32.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&message)))
			user32.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&message)))
		}
	}()
}
