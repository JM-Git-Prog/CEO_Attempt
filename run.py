"""Run The Living Room web server. Usage: python run.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=True)
