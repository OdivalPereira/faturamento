import uvicorn
from backend.app.main import app

if __name__ == "__main__":
    # Hide console on Windows if possible
    try:
        import ctypes
        import os
        if os.name == 'nt':
            kernel32 = ctypes.windll.kernel32
            kernel32.FreeConsole()
    except:
        pass
        
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
