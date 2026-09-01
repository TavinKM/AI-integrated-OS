# neo4j_load_parquet.py
"""
Load GraphRAG Parquet outputs into a local Neo4j, create vector index,
and store sentence-transformers/all-MiniLM-L6-v2 embeddings on Entity.embedding.

Usage:
    python neo4j_load_parquet.py \
      --entities graphrag/output/entities.parquet \
      --relationships graphrag/output/relationships.parquet \
      --textunits graphrag/output/text_units.parquet \
      --batch 64

If relationships/textunits paths omitted, script will skip those steps.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Import your local neo4j config file that you already have in repo
import sys
from pathlib import Path

# Add parent directory to path to find neo4j_config.py
script_dir = Path(__file__).parent
parent_dir = script_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

try:
    from neo4j_config import URI, USER, PASSWORD
except ImportError:
    # Try scripts directory as fallback
    try:
        sys.path.insert(0, str(script_dir))
        from neo4j_config import URI, USER, PASSWORD
    except ImportError as e:
        raise SystemExit("Make sure neo4j_config.py exists in project root or scripts/ and sets URI, USER, PASSWORD") from e


EMBED_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def clear_database(driver):
    """Clear all Entity, TextUnit nodes and RELATED relationships."""
    with driver.session() as session:
        # Delete relationships first
        result = session.run("MATCH ()-[r:RELATED]->() DELETE r RETURN count(r) as deleted")
        rel_count = result.single()['deleted']
        
        # Delete all nodes
        result = session.run("MATCH (n) WHERE n:Entity OR n:TextUnit DELETE n RETURN count(n) as deleted")
        node_count = result.single()['deleted']
        
        print(f"Cleared {node_count} nodes and {rel_count} relationships.")


def ensure_schema(driver):
    """Create constraints + vector index (Neo4j 5.15+ syntax)."""
    schema_cmds = [
        """
        CREATE CONSTRAINT entity_id IF NOT EXISTS
        FOR (e:Entity)
        REQUIRE e.id IS UNIQUE;
        """,
        """
        CREATE CONSTRAINT textunit_id IF NOT EXISTS
        FOR (t:TextUnit)
        REQUIRE t.id IS UNIQUE;
        """,
        """
        CREATE INDEX entity_title_idx IF NOT EXISTS
        FOR (e:Entity)
        ON (e.title);
        """,
        f"""
        CREATE VECTOR INDEX entity_embedding_idx
        IF NOT EXISTS
        FOR (e:Entity)
        ON (e.embedding)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {EMBED_DIM},
            `vector.similarity_function`: 'cosine'
          }}
        }};
        """,
    ]
    with driver.session() as session:
        for cmd in schema_cmds:
            try:
                session.run(cmd)
            except Exception as e:
                # Some commands might fail if they already exist, that's okay
                print(f"Note: {e}")
    print("Schema + vector index ensured.")


def read_parquet_flexible(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    df = pd.read_parquet(path)
    return df


def text_for_embedding(row: Dict) -> str:
    # prefer description, then title, then fallback to concatenating fields
    desc = row.get("description") or row.get("desc") or ""
    title = row.get("title") or row.get("name") or ""
    extras = []
    for k in ("type", "human_readable_id", "frequency", "degree"):
        if k in row and pd.notna(row[k]):
            extras.append(f"{k}:{row[k]}")
    base = " ".join([title, desc] + extras).strip()
    return base if base else title or desc or ""


def upsert_entities(driver, entities_iter, embed_fn, batch_size=64):
    """
    entities_iter yields dict-like objects for each entity.
    embed_fn(list[str]) -> np.ndarray of shape (N, EMBED_DIM)
    """
    def _tx_upsert(tx, batch_entities, vectors):
        query = """
        UNWIND $rows AS r
        MERGE (e:Entity {id: r.id})
        SET e.title = r.title,
            e.type = r.type,
            e.description = r.description,
            e.human_readable_id = r.human_readable_id,
            e.frequency = r.frequency,
            e.degree = r.degree,
            e.text_unit_ids = r.text_unit_ids,
            e.embedding = r.embedding
        """
        params = {"rows": []}
        for ent, vec in zip(batch_entities, vectors):
            # Safely normalise text_unit_ids without using truthiness or pd.isna on arrays
            raw_ids = ent.get("text_unit_ids", None)

            text_unit_ids = []
            if raw_ids is None:
                text_unit_ids = []
            else:
                # If it's list/tuple/ndarray-like, treat as already a collection
                if hasattr(raw_ids, "tolist") or isinstance(raw_ids, (list, tuple, set)):
                    text_unit_ids = raw_ids
                else:
                    # Scalar value – only here we care about NaN
                    if pd.isna(raw_ids):
                        text_unit_ids = []
                    else:
                        text_unit_ids = [raw_ids]

            # Convert to a plain Python list
            if hasattr(text_unit_ids, "tolist"):
                text_unit_ids = text_unit_ids.tolist()
            elif isinstance(text_unit_ids, (set, tuple)):
                text_unit_ids = list(text_unit_ids)
            elif not isinstance(text_unit_ids, list):
                text_unit_ids = [text_unit_ids]

            # Neo4j driver needs Python lists for list properties
            params["rows"].append(
                {
                    "id": ent.get("id"),
                    "title": ent.get("title"),
                    "type": ent.get("type"),
                    "description": ent.get("description"),
                    "human_readable_id": ent.get("human_readable_id"),
                    "frequency": ent.get("frequency"),
                    "degree": ent.get("degree"),
                    "text_unit_ids": text_unit_ids,
                    "embedding": vec.tolist(),
                }
            )
        tx.run(query, **params)

    batch = []
    texts = []
    count = 0
    with driver.session() as session:
        for ent in entities_iter:
            batch.append(ent)
            texts.append(text_for_embedding(ent))
            if len(batch) >= batch_size:
                vectors = embed_fn(texts)
                session.execute_write(_tx_upsert, batch, vectors)
                count += len(batch)
                tqdm.write(f"Upserted {count} entities")
                batch = []
                texts = []
        if batch:
            vectors = embed_fn(texts)
            session.execute_write(_tx_upsert, batch, vectors)
            count += len(batch)
            tqdm.write(f"Upserted {count} entities")

    print(f"Finished upserting {count} entities.")


def upsert_textunits(driver, textunits_df, batch_size=128):
    def _tx_upsert(tx, rows):
        q = """
        UNWIND $rows AS r
        MERGE (t:TextUnit {id: r.id})
        SET t.text = r.text,
            t.source = r.source
        """
        tx.run(q, rows=rows)

    rows = []
    count = 0
    with driver.session() as session:
        for _, r in textunits_df.iterrows():
            rows.append({"id": r.get("id"), "text": r.get("text") or r.get("content") or "" , "source": r.get("source")})
            if len(rows) >= batch_size:
                session.execute_write(_tx_upsert, rows)
                count += len(rows)
                tqdm.write(f"Upserted {count} text units")
                rows = []
        if rows:
            session.execute_write(_tx_upsert, rows)
            count += len(rows)
    print(f"Finished upserting {count} text units.")


def upsert_relationships(driver, rels_df, batch_size=256):
    # Try to detect column names for source/target/kind/weight
    src_candidates = ["source", "source_id", "from", "a", "src"]
    dst_candidates = ["target", "target_id", "to", "b", "dst"]
    kind_candidates = ["type", "relation_type", "kind", "label"]
    weight_candidates = ["weight", "score"]

    src_col = next((c for c in src_candidates if c in rels_df.columns), None)
    dst_col = next((c for c in dst_candidates if c in rels_df.columns), None)
    kind_col = next((c for c in kind_candidates if c in rels_df.columns), None)
    weight_col = next((c for c in weight_candidates if c in rels_df.columns), None)

    if not src_col or not dst_col:
        print("No recognizable source/target columns found in relationships. Skipping relationships load.")
        return

    def _tx_upsert(tx, rows):
        # Try matching by title first (since relationships use titles like 'LS', '-L')
        # If that fails, fall back to matching by id
        q = """
        UNWIND $rows AS r
        MATCH (a:Entity)
        WHERE a.title = r.src OR a.id = r.src
        MATCH (b:Entity)
        WHERE b.title = r.dst OR b.id = r.dst
        MERGE (a)-[rel:RELATED]->(b)
        SET rel.kind = r.kind,
            rel.weight = r.weight,
            rel.description = r.description,
            rel.id = r.id,
            rel.human_readable_id = r.human_readable_id,
            rel.combined_degree = r.combined_degree,
            rel.text_unit_ids = r.text_unit_ids
        """
        tx.run(q, rows=rows)

    rows = []
    count = 0
    with driver.session() as session:
        for _, r in rels_df.iterrows():
            # Convert text_unit_ids to list if it's a numpy array
            text_unit_ids = r.get("text_unit_ids") if "text_unit_ids" in rels_df.columns else None
            if text_unit_ids is not None:
                if hasattr(text_unit_ids, 'tolist'):
                    text_unit_ids = text_unit_ids.tolist()
                elif not isinstance(text_unit_ids, list) and pd.notna(text_unit_ids):
                    text_unit_ids = list(text_unit_ids) if text_unit_ids else []
                elif pd.isna(text_unit_ids):
                    text_unit_ids = []
            else:
                text_unit_ids = []
            
            row_data = {
                "src": r.get(src_col),
                "dst": r.get(dst_col),
                "kind": r.get(kind_col) if kind_col else "RELATED",
                "weight": float(r.get(weight_col)) if weight_col and pd.notna(r.get(weight_col)) else 1.0,
                "description": r.get("description") if "description" in rels_df.columns and pd.notna(r.get("description")) else None,
                "id": r.get("id") if "id" in rels_df.columns and pd.notna(r.get("id")) else None,
                "human_readable_id": int(r.get("human_readable_id")) if "human_readable_id" in rels_df.columns and pd.notna(r.get("human_readable_id")) else None,
                "combined_degree": int(r.get("combined_degree")) if "combined_degree" in rels_df.columns and pd.notna(r.get("combined_degree")) else None,
                "text_unit_ids": text_unit_ids
            }
            rows.append(row_data)
            if len(rows) >= batch_size:
                session.execute_write(_tx_upsert, rows)
                count += len(rows)
                tqdm.write(f"Upserted {count} relationships")
                rows = []
        if rows:
            session.execute_write(_tx_upsert, rows)
            count += len(rows)
    print(f"Finished upserting {count} relationships.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--entities", type=Path, default=Path("graphrag/output/entities.parquet"))
    p.add_argument("--relationships", type=Path, default=Path("graphrag/output/relationships.parquet"))
    p.add_argument("--textunits", type=Path, default=Path("graphrag/output/text_units.parquet"))
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--clear", action="store_true", help="Clear all existing Entity, TextUnit nodes and RELATED relationships before loading")
    args = p.parse_args()
    model = SentenceTransformer(MODEL_NAME)
    print(f"Loaded embedding model: {MODEL_NAME}")

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD), max_connection_lifetime=3600)

    try:
        if args.clear:
            clear_database(driver)
        ensure_schema(driver)

        # Entities
        if not args.entities.exists():
            raise SystemExit(f"Entities file not found: {args.entities}")
        df_entities = read_parquet_flexible(args.entities)
        # convert dataframe to iterator of dicts
        # if your parquet has nested structures, convert safely
        ent_iter = (row._asdict() if hasattr(row, "_asdict") else row.to_dict() for _, row in df_entities.iterrows())

        def embed_batch(texts: List[str]) -> np.ndarray:
            arr = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            # ensure shape correct
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.shape[1] != EMBED_DIM:
                raise RuntimeError(f"Embedding dimension mismatch: expected {EMBED_DIM}, got {arr.shape[1]}")
            return arr

        upsert_entities(driver, ent_iter, embed_batch, batch_size=args.batch)

        # Text units (optional)
        if args.textunits.exists():
            df_textunits = read_parquet_flexible(args.textunits)
            upsert_textunits(driver, df_textunits)
        else:
            print("No text_units.parquet found, skipping text units.")

        # Relationships (optional)
        if args.relationships.exists():
            df_rels = read_parquet_flexible(args.relationships)
            if df_rels.shape[0] > 0:
                upsert_relationships(driver, df_rels)
            else:
                print("relationships.parquet empty, skipping.")
        else:
            print("No relationships.parquet found, skipping relationships.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
