import uvicorn
import os
import sys

# Ensure src is in pythonpath if running directly (though installed package preferred)
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

if __name__ == "__main__":
    uvicorn.run("sandbox_runtime.api:app", host="0.0.0.0", port=8000, reload=True)
