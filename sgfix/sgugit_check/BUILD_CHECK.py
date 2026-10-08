"""Production dependency preflight; exits non-zero if a required runtime import is missing."""
mods = ["openpyxl", "requests", "telegram", "fastapi", "uvicorn", "dotenv"]
for name in mods:
    __import__(name)
print("OK: runtime dependencies imported")
