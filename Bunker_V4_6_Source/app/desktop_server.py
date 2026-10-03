"""Private desktop entry point. Does not install packages or modify the system."""
import os, sys, logging, logging.handlers, asyncio
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("BUNKER_MANAGE_FIREWALL", "0")
os.environ.setdefault("BUNKER_EXTERNAL_LOOKUP", "0")
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def main():
    import uvicorn
    port = int(os.environ.get("PORT", "8008"))
    host = "127.0.0.1" if os.getenv("BUNKER_CONNECTION_MODE") == "porthole" else "0.0.0.0"
    uvicorn.run("server.app:app", host=host, port=port, loop="asyncio", http="h11",
                ws="websockets", proxy_headers=False, use_colors=False, access_log=False)

if __name__ == "__main__":
    main()
