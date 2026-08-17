import os, sys, time

os.environ["LANGCHAIN_PROVIDER"] = "ollama"
os.environ["LANGCHAIN_MODEL_NAME"] = "vibe-qwen3-4b-64k:latest"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
os.environ["OPENAI_API_KEY"] = "ollama"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.memory.persistent import PersistentMemory
from src.tools import build_registry

event_cb = lambda et, data: None
warn_cb = lambda msg: None

print("building registry (no shell, default config)...", flush=True)
start = time.monotonic()
registry = build_registry(
    persistent_memory=PersistentMemory(),
    include_shell_tools=False,
    agent_config={},
    session_id="test-session",
    event_callback=event_cb,
    warn_callback=warn_cb,
)
print(f"registry built in {time.monotonic()-start:.1f}s")
print(f"tool names: {list(registry.tools.keys())[:20]}...")
