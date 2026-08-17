import os, sys, time

os.environ["LANGCHAIN_PROVIDER"] = "ollama"
os.environ["LANGCHAIN_MODEL_NAME"] = "vibe-qwen3-4b-64k:latest"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
os.environ["OPENAI_API_KEY"] = "ollama"
os.environ["TIMEOUT_SECONDS"] = "30"
os.environ["MAX_RETRIES"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.providers.chat import ChatLLM

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Return the current time as HH:MM:SS.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]

messages = [
    {"role": "system", "content": "You are a helpful assistant. Use tools if needed."},
    {"role": "user", "content": "What time is it?"},
]

llm = ChatLLM()

print("testing stream_chat with one tool...", flush=True)
start = time.monotonic()
try:
    resp = llm.stream_chat(messages, tools=tools, on_text_chunk=lambda c: print(f"  chunk: {c!r}", flush=True))
    print(f"response in {time.monotonic()-start:.1f}s: content={resp.content!r} tool_calls={[(tc.name, tc.arguments) for tc in resp.tool_calls]}")
except Exception as e:
    print(f"error in {time.monotonic()-start:.1f}s: {type(e).__name__}: {e}")
