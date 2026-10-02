import os
import sys
import time
import socket
import subprocess
import urllib.parse
from app.config import settings

def wait_for_database():
    db_url = settings.DATABASE_URL
    if "postgresql" in db_url:
        print("Detected PostgreSQL database. Waiting for database readiness...")
        parsed = urllib.parse.urlparse(db_url)
        host = parsed.hostname or "postgres"
        port = parsed.port or 5432
        
        max_attempts = 30
        for attempt in range(1, max_attempts + 1):
            try:
                with socket.create_connection((host, port), timeout=2.0):
                    print(f"Database at {host}:{port} is ready!")
                    return
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                print(f"Attempt {attempt}/{max_attempts}: Database at {host}:{port} not ready yet ({e}). Waiting 1s...")
                time.sleep(1)
        
        print("Warning: Database connection check timed out. Continuing startup...")

def run_migrations():
    print("Running database migrations (alembic upgrade head)...")
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Alembic migration failed with code {result.returncode}:")
        print(result.stdout)
        print(result.stderr)
        # Continue or exit depending on desired resiliency
    else:
        print("Database migrations applied successfully.")

def main():
    wait_for_database()
    run_migrations()
    
    # Run the CMD arguments passed to docker container
    cmd = sys.argv[1:] if len(sys.argv) > 1 else ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    print(f"Starting server with command: {' '.join(cmd)}")
    os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
