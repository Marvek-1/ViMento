import os
import sys
import time

# Configure before provider env loader uses .env defaults
os.environ["LANGCHAIN_PROVIDER"] = "ollama"
os.environ["LANGCHAIN_MODEL_NAME"] = "vibe-qwen3-4b-64k:latest"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:11434/v1"
os.environ["OPENAI_API_KEY"] = "ollama"
os.environ["TIMEOUT_SECONDS"] = "60"
os.environ["MAX_RETRIES"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.providers.chat import ChatLLM

llm = ChatLLM()

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Say hello in exactly two words."},
]

print("testing chat (no tools)...", flush=True)
start = time.monotonic()
try:
    resp = llm.chat(messages)
    print(f"response in {time.monotonic()-start:.1f}s: {resp.content!r}")
except Exception as e:
    print(f"error in {time.monotonic()-start:.1f}s: {type(e).__name__}: {e}")

print("testing stream_chat (no tools)...", flush=True)
start = time.monotonic()
chunks = []
try:
    resp = llm.stream_chat(messages, on_text_chunk=lambda c: chunks.append(c))
    print(f"response in {time.monotonic()-start:.1f}s: {resp.content!r} chunks={len(chunks)}")
except Exception as e:
    print(f"error in {time.monotonic()-start:.1f}s: {type(e).__name__}: {e}")
