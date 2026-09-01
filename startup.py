"""
Startup script for Desktop Agent Docker container.
Handles Neo4j initialization, data import, Docker Model Runner setup, and running main.py
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import requests

# Configuration from environment variables
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphrag")
LLM_URL = os.getenv("LLM_URL", "http://model-runner.docker.internal/engines/v1")
LLM_MODEL = os.getenv("LLM_MODEL")
MODEL_RUNNER_PORT = int(os.getenv("MODEL_RUNNER_PORT", "12434"))

# Paths
SCRIPT_DIR = Path("/app")
ENTITIES_PATH = SCRIPT_DIR / "graphrag" / "output" / "entities.parquet"
RELATIONSHIPS_PATH = SCRIPT_DIR / "graphrag" / "output" / "relationships.parquet"
TEXTUNITS_PATH = SCRIPT_DIR / "graphrag" / "output" / "text_units.parquet"


def wait_for_neo4j(max_retries=30, delay=2):
    """Wait for Neo4j to be ready."""
    from neo4j import GraphDatabase
    
    print(f"Waiting for Neo4j at {NEO4J_URI}...")
    for i in range(max_retries):
        try:
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            with driver.session() as session:
                session.run("RETURN 1")
            driver.close()
            print("Neo4j is ready")
            return True
        except Exception as e:
            if i < max_retries - 1:
                print(f"Neo4j not ready yet ({i+1}/{max_retries}), waiting {delay}s...")
                time.sleep(delay)
            else:
                print(f"Failed to connect to Neo4j: {e}")
                return False
    return False


def wait_for_llm(max_retries=60, delay=5):
    """Wait for Docker Model Runner to be up."""
    parsed = urlparse(LLM_URL.rstrip("/"))
    #with fixed file paths this might not be needed
    host = parsed.netloc.split(":")[0] if parsed.netloc else "model-runner.docker.internal"
    port = int(parsed.port) if parsed.port else MODEL_RUNNER_PORT
    origin = f"{parsed.scheme}://{host}:{port}"
    base_url = f"{origin}/engines/v1"
    health_url = f"{base_url}/models"
    #polling loop
    print(f"Polling Model Runner at: {health_url}")
    for i in range(max_retries):
        try:
            response = requests.get(health_url, timeout=10)
            if response.status_code == 200:
                print("Model Runner is ready.")
                return True
            if i == 0 or i % 10 == 0:
                print(f"Model Runner returned {response.status_code}, retrying...")
        except requests.exceptions.RequestException as e:
            if i == 0 or i % 10 == 0:
                print(f"Model Runner not reachable: {e}")
        except Exception as e:
            if i == 0 or i % 10 == 0:
                print(f"Error: {e}")

        if i % 5 == 0 and i > 0:
            print(f"Waiting... ({i}/{max_retries})")
        time.sleep(delay)
    return False


def check_neo4j_has_data():
    """Check if Neo4j already has entities."""
    from neo4j import GraphDatabase
    
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            result = session.run("MATCH (e:Entity) RETURN count(e) as count")
            count = result.single()["count"]
            driver.close()
            return count > 0
    except Exception as e:
        print(f"Error checking Neo4j data: {e}")
        return False


def import_data_to_neo4j():
    print("Importing data into Neo4j...")
    
    config_file = SCRIPT_DIR / "neo4j_config.py"
    print(f"Creating/updating {config_file}...")
    with open(config_file, "w") as f:
        f.write(f'URI = "{NEO4J_URI}"\n')
        f.write(f'USER = "{NEO4J_USER}"\n')
        f.write(f'PASSWORD = "{NEO4J_PASSWORD}"\n')
    
    # Also create it in scripts/ directory since jsontograph.py imports from there
    scripts_config = SCRIPT_DIR / "scripts" / "neo4j_config.py"
    scripts_config.parent.mkdir(parents=True, exist_ok=True)
    with open(scripts_config, "w") as f:
        f.write(f'URI = "{NEO4J_URI}"\n')
        f.write(f'USER = "{NEO4J_USER}"\n')
        f.write(f'PASSWORD = "{NEO4J_PASSWORD}"\n')
    
    # Check if parquet files exist
    if not ENTITIES_PATH.exists():
        print(f"Warning: {ENTITIES_PATH} not found. Skipping data import.")
        return False
    
    # Run the import script
    import_script = SCRIPT_DIR / "scripts" / "jsontograph.py"
    if not import_script.exists():
        print(f"Error: {import_script} not found")
        return False
    
    cmd = [
        sys.executable,
        str(import_script),
        "--entities", str(ENTITIES_PATH),
        "--relationships", str(RELATIONSHIPS_PATH),
        "--textunits", str(TEXTUNITS_PATH),
        "--batch", "64"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    
    if result.returncode == 0:
        print("Data import completed successfully")
        return True
    else:
        print(f"Data import failed with return code {result.returncode}")
        return False


def ensure_dmr_ready():
    """Verify Docker Model Runner is responsive."""
    parsed = urlparse(LLM_URL.rstrip("/"))
    host = parsed.netloc.split(":")[0] if parsed.netloc else "model-runner.docker.internal"
    port = int(parsed.port) if parsed.port else MODEL_RUNNER_PORT
    origin = f"{parsed.scheme}://{host}:{port}"
    models_url = f"{origin}/engines/v1/models"

    print(f"Verifying Model Runner at: {models_url}")
    try:
        response = requests.get(models_url, timeout=10)
        if response.status_code == 200:
            print("Docker Model Runner is ready.")
            return True
        print(f"Model Runner returned status: {response.status_code}")
        return False
    except Exception as e:
        print(f"Connection error: {e}")
        return False


def main():
    print("Desktop Agent Startup")
    
    config_file = SCRIPT_DIR / "neo4j_config.py"
    print(f"Creating/updating {config_file}...")
    with open(config_file, "w") as f:
        f.write(f'URI = "{NEO4J_URI}"\n')
        f.write(f'USER = "{NEO4J_USER}"\n')
        f.write(f'PASSWORD = "{NEO4J_PASSWORD}"\n')
    
    # Wait for Neo4j
    if not wait_for_neo4j():
        print("ERROR: Neo4j failed to start")
        sys.exit(1)
    
    # Check if Neo4j has data, import if not
    if not check_neo4j_has_data():
        print("Neo4j database is empty, importing data...")
        if ENTITIES_PATH.exists():
            if not import_data_to_neo4j():
                print("WARNING: Data import failed, but continuing...")
        else:
            print(f"WARNING: {ENTITIES_PATH} not found. Run GraphRAG indexing first.")
    else:
        print("Neo4j already has data, skipping import")
    
    # Do not block on LLM so the web GUI starts immediately and is reachable in the browser.
    print("Checking Model Runner (non-blocking)...")
    if wait_for_llm(max_retries=2, delay=2):
        ensure_dmr_ready()
    else:
        print("WARNING: Model Runner not reachable. Command generation will fail until it is available.")

    # Run web GUI (container stays up; access at the configured host/port)
    print("Starting Desktop Agent Web GUI...")
    
    web_app_script = SCRIPT_DIR / "web_app.py"
    if not web_app_script.exists():
        print(f"ERROR: {web_app_script} not found")
        sys.exit(1)
    
    os.environ["LLM_URL"] = LLM_URL
    os.environ["LLM_MODEL"] = LLM_MODEL or ""
    
    sys.path.insert(0, str(SCRIPT_DIR))
    import web_app
    web_app.run_server()


if __name__ == "__main__":
    main()

