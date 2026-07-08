uvicorn backend.main:app --host 0.0.0.0 --port 7860 --reload

cloudflared tunnel --url http://127.0.0.1:7860