import os
import sys
import time
import signal
import subprocess
import webbrowser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def check_env():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print("ERROR: .env file not found. Run setup.py first.")
        sys.exit(1)
    print("[OK] .env found")


def check_postgres():
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            database=os.getenv("POSTGRES_DB", "finance_agent"),
        )
        conn.close()
        print("[OK] PostgreSQL connection successful")
    except Exception as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}")
        print("Make sure PostgreSQL is running and finance_agent database exists.")
        print("Run 'python setup.py' first.")
        sys.exit(1)


def check_generated_dir():
    generated = Path(__file__).parent / "generated"
    generated.mkdir(exist_ok=True)
    print("[OK] generated/ directory ready")


def wait_for_server(url: str, timeout: int = 30):
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    print("=" * 50)
    print("  Finance Agent — Startup Checks")
    print("=" * 50)

    check_env()
    check_postgres()
    check_generated_dir()

    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8501"))
    url = f"http://localhost:{port}"

    print(f"\nStarting server on {url} ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "service:app",
         "--host", host, "--port", str(port)],
        cwd=str(Path(__file__).parent),
    )

    if wait_for_server(url):
        print(f"[OK] Server is running at {url}")
        webbrowser.open(url)
    else:
        print("WARNING: Server did not respond in time, opening browser anyway.")
        webbrowser.open(url)

    print("\nPress Ctrl+C to shut down.\n")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("Goodbye!")


if __name__ == "__main__":
    main()
