## Desktop Agent for ELEC 498

A Python-based desktop agent that builds a knowledge graph over Unix command documentation using GraphRAG, loads that graph into Neo4j, and uses Docker Model Runner to generate grounded shell commands from natural language.

---

### Dependencies

**For Docker Compose (recommended):**

- Docker and Docker Compose
- Docker Model Runner (DMR) on the host. Enable in Docker Desktop (Settings > Features) and expose TCP on port 12434: `docker desktop enable model-runner --tcp 12434`. The desktop-agent container talks to DMR at `model-runner.docker.internal:12434`.

---

### Setup and run

#### Docker Compose

1. Clone the repo and go to the project directory.

2. (Optional) Pre-pull models so the app can use them without delay. Run once:
   ```bash
   ./docker-model-pull.sh
   ```
   This pulls the LLM and embedding models into Docker Model Runner’s cache. Compose does not provision models; the desktop-agent container connects to DMR on the host.

3. Start services:
   ```bash
   docker compose up -d
   ```
   This starts Neo4j (ports 7474, 7687) and the desktop-agent app. Startup waits for Neo4j, optionally checks Model Runner, then runs the web GUI. The app listens on port 5000 by default (override with `GUI_PORT` if needed).

4. Open the web GUI at http://localhost:5000. You get an input bar, a workspace file list (contents of `workspace/`), and a panel that shows the generated command and its output.

5. Stop everything:
   ```bash
   docker compose down
   ```
   Containers are removed. The `neo4j_data` volume and your `workspace/` directory are left in place.

---
If you need to re-index GraphRAG from scratch:
```bash
uv run graphrag index --config graphrag/settings.yaml
```
This reads from `graphrag/input/` and writes Parquet files to `graphrag/output/`. All `.txt` files in `graphrag/input/` must be UTF-8 (the repo’s are already converted).

**Refreshing input data:** this project uses manpages and tldr pages to build a knowledge graph of commands and their related flags, targets. You can manually upload text related to this topic, however the configuration in `graphrag/settings.yaml` explicitly looks for [COMMAND, OPTION, ARGUMENT, FILE, CONCEPT].

---

**Load new graph into Neo4j** (after re-indexing or when `graphrag/output/` has new parquet files). With Docker Compose running, from project root (one line; PowerShell doesn't use `\` for line continuation):
```bash
docker compose exec desktop-agent uv run python /app/scripts/jsontograph.py --entities /app/graphrag/output/entities.parquet --relationships /app/graphrag/output/relationships.parquet --textunits /app/graphrag/output/text_units.parquet --batch 64 --clear
```
`--clear` replaces existing Entity/TextUnit/RELATED data. Local: `uv run python scripts/jsontograph.py --entities graphrag/output/entities.parquet --relationships graphrag/output/relationships.parquet --textunits graphrag/output/text_units.parquet --batch 64 --clear` (requires `neo4j_config.py`).

**View the graph:** http://localhost:7474 (Neo4j Browser), login `neo4j` / `graphrag`. Example: `MATCH (a:Entity)-[r:RELATED]-(b:Entity) RETURN a, r, b LIMIT 100` (use graph view in result panel).

---

### Managing dependencies

Dependencies are managed with uv via `pyproject.toml` and `uv.lock`.

- Add or remove a package:
  ```bash
  uv add package-name
  uv sync
  ```

- Run a script with the project environment:
  ```bash
  uv run python scripts/jsontograph.py ...
  uv run python main.py
  uv run graphrag index --config graphrag/settings.yaml
  ```

---

### Development notes

- **GraphRAG/Neo4j:** Entity embeddings in Neo4j are created by `jsontograph.py` (SentenceTransformer), not by GraphRAG's pipeline. The agent only needs `entities.parquet` and `relationships.parquet` (produced by `finalize_graph`); you can skip `create_community_reports` and `generate_text_embeddings` if not using GraphRAG query. Embedding model in `graphrag/settings.yaml` uses `api_base: http://localhost:11434/v1` and `model_provider: openai` for Ollama compatibility.

- The `graphrag` folder is large and is included so indexing isn't required, as it's more intensive on the GPU than querying. 

- In Docker, `neo4j_config.py` is created at startup by `startup.py`; you do not need it in the repo.

- If Neo4j connection fails, confirm Neo4j is running and that `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` match your instance.

- If Model Runner calls fail, confirm DMR is enabled and listening on the expected port, and that the models used by `LLM_MODEL` and `EMBEDDING_MODEL` are available (e.g. pulled via `docker-model-pull.sh`).
