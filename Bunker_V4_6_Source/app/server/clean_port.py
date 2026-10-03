import subprocess
import sys

def free_port(port: int = 8008):
    try:
        out = subprocess.check_output('netstat -ano', shell=True).decode(errors='ignore')
        for line in out.splitlines():
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    try:
                        # /T kills process and all child/parent tree processes
                        subprocess.run(f'taskkill /T /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
    except Exception:
        pass

    # Also cleanup any lingering uvicorn/python server processes on Windows
    try:
        wmic_out = subprocess.check_output('wmic process where "name=\'python.exe\'" get ProcessId,CommandLine', shell=True).decode(errors='ignore')
        for line in wmic_out.splitlines():
            if 'server.app:app' in line:
                parts = line.strip().split()
                if parts and parts[-1].isdigit():
                    pid = parts[-1]
                    try:
                        subprocess.run(f'taskkill /T /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
    except Exception:
        pass

if __name__ == '__main__':
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8008
    free_port(p)
