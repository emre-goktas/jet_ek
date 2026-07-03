import asyncio
from backend.services.ai_service import jet_rename_pdf

try:
    print(jet_rename_pdf("019a23f916654801ac75174ffc13b70b"))
except Exception as e:
    import traceback
    traceback.print_exc()
