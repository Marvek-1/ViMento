import os, sys, time, threading

os.environ["LANGCHAIN_PROVIDER"] = "ollama"
os.environ["LANGCHAIN_MODEL_NAME"] = "vibe-qwen3-4b-64k:latest"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
os.environ["OPENAI_API_KEY"] = "ollama"
os.environ["TIMEOUT_SECONDS"] = "60"
os.environ["MAX_RETRIES"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.memory.persistent import PersistentMemory
from src.providers.chat import ChatLLM
from src.tools import build_filtered_registry
from src.agent.loop import AgentLoop

events = []
def event_callback(event_type, data):
    events.append((event_type, data))
    print(f"event: {event_type} {data}", flush=True)

pm = PersistentMemory()
print("building filtered registry...", flush=True)
registry = build_filtered_registry(
    tool_names=["get_current_time"],
    include_shell_tools=False,
)
print(f"registry has {len(registry._tools)} tools", flush=True)

llm = ChatLLM()
agent = AgentLoop(registry=registry, llm=llm, max_iterations=2, persistent_memory=pm, event_callback=event_callback)

print("starting AgentLoop.run('hello') with max_iterations=2", flush=True)
start = time.monotonic()
result = agent.run(user_message="hello", history=None, session_id="test-agent-loop-small")
print(f"completed in {time.monotonic()-start:.1f}s")
print(f"result keys: {result.keys()}")
print(f"content preview: {result.get('content','')[:300]!r}")
