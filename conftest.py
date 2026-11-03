# Ensures the project root is on sys.path so tests can `import scoring`/`import main`.
#
# Tests must be fully deterministic and offline: blank the LLM key BEFORE main.py
# loads .env (os.environ.setdefault will not override an existing empty value),
# so every test hits the template fallback instead of the network.
import os

os.environ.setdefault("GEMINI_API_KEY", "")
