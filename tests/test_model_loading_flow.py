
import asyncio
import json
import os
import sys
import shutil
import tempfile
from pathlib import Path

# Add agent to path
AGENT_DIR = os.path.join(os.path.dirname(__file__), "..", "agent")
sys.path.insert(0, os.path.abspath(AGENT_DIR))

async def test_load_flow():
    """
    Integration test for the load_model flow.
    It spawns the agent/main.py and sends a load_model message.
    """
    # 1. Use the real model path
    model_path = "/Users/tianhaozhou/models/cyberpaw/gemma-4-E2B-it-Q4_K_M.gguf"
    if not os.path.exists(model_path):
        print(f"SKIPPING: Real model path {model_path} does not exist.")
        return

    # 2. Spawn agent/main.py
    # We use the .venv python to ensure dependencies are present
    python_exe = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python3")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    process = await asyncio.create_subprocess_exec(
        python_exe, os.path.join(AGENT_DIR, "main.py"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=AGENT_DIR
    )

    # 3. Send load_model message
    load_msg = {
        "type": "load_model",
        "model_path": model_path,
        "backend": "llamacpp"
    }
    process.stdin.write((json.dumps(load_msg) + "\n").encode())
    await process.stdin.drain()

    # 4. Listen for results
    success = False
    error_msg = None
    
    try:
        # Wait up to 30 seconds for loading to complete or fail
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=30.0)
            if not line:
                break
            
            line_str = line.decode().strip()
            if not line_str.startswith("{"):
                print(f"Agent log: {line_str}")
                continue
            
            try:
                event = json.loads(line_str)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON: {line_str}")
                continue
                
            print(f"Received event: {event.get('type')}")
            
            if event.get("type") == "model_status" and event.get("loaded") is True:
                success = True
                break
            elif event.get("type") == "error":
                error_msg = event.get("message")
                break
    except asyncio.TimeoutError:
        error_msg = "Timeout waiting for model load"
    finally:
        process.terminate()
        await process.wait()

    # 5. Assertions
    if success:
        print("PASS: Model loaded successfully via flow!")
    else:
        print(f"FAIL: Model load failed: {error_msg}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_load_flow())
