"""Liara Python entry point.

Liara's Python console starts ``python3 main.py``. Keep this tiny launcher
separate from the interview API so local development can still use
``uvicorn server:app --reload``.
"""
import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "80")), proxy_headers=True)
