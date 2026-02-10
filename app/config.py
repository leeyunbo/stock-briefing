import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
DART_API_KEY = os.getenv("DART_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# AI Provider: "claude" or "gemini"
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude")

# SMTP
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///briefing.db")
