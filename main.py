from neo4j import GraphDatabase
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer
import numpy as np
import requests
import json
import os
from urllib.parse import urlparse


class Neo4jGraphQuery:
    """Query interface for Neo4j knowledge graph."""
    
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        
        self.driver.verify_connectivity()

        # defaults for dmr
        raw_url = os.getenv("EMBEDDING_URL", "http://model-runner.docker.internal:12434/engines/v1")
        parsed = urlparse(raw_url.rstrip("/"))
        host = parsed.netloc.split(":")[0] if parsed.netloc else "model-runner.docker.internal"
        port = parsed.port or int(os.getenv("MODEL_RUNNER_PORT", "12434"))
        self.dmr_base = f"{parsed.scheme}://{host}:{port}/engines/v1"
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "hf.co/Mungert/all-MiniLM-L6-v2-GGUF:q8_0")

    def _get_embedding(self, text: str) -> List[float]:
        endpoint = f"{self.dmr_base}/embeddings"
        
        payload = {
            "model": self.embedding_model,
            "input": text
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=60)
            
            # If DMR returns 500 print code
            if response.status_code != 200:
                print(f"DMR Error {response.status_code}: {response.text}")
                response.raise_for_status()
                
            data = response.json()
            return data['data'][0]['embedding']
        except Exception as e:
            print(f"Critical Error: Embedding failed. Details: {e}")
            raise e
        
    def close(self):
        """Close the database connection."""
        self.driver.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def search_entities_by_text(
        self, 
        query_text: str, 
        entity_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search entities by matching text in title or description.
        
        Args:
            query_text: Text to search for
            entity_type: Optional filter by entity type 
            limit: Maximum number of results
            
        Returns:
            List of entity dictionaries
        """
        with self.driver.session() as session:
            if entity_type:
                cypher_query = """
                MATCH (e:Entity)
                WHERE (toLower(e.title) CONTAINS toLower($search_text) 
                       OR toLower(e.description) CONTAINS toLower($search_text))
                      AND e.type = $entity_type
                RETURN e.id as id, e.title as title, e.type as type, 
                       e.description as description, e.frequency as frequency,
                       e.degree as degree
                ORDER BY e.frequency DESC, e.degree DESC
                LIMIT $limit
                """
                result = session.run(cypher_query, search_text=query_text, entity_type=entity_type, limit=limit)
            else:
                cypher_query = """
                MATCH (e:Entity)
                WHERE toLower(e.title) CONTAINS toLower($search_text) 
                   OR toLower(e.description) CONTAINS toLower($search_text)
                RETURN e.id as id, e.title as title, e.type as type, 
                       e.description as description, e.frequency as frequency,
                       e.degree as degree
                ORDER BY e.frequency DESC, e.degree DESC
                LIMIT $limit
                """
                result = session.run(cypher_query, search_text=query_text, limit=limit)
            
            return [dict(record) for record in result]
    
    def semantic_search(
        self, 
        query_text: str, 
        entity_type: Optional[str] = None,
        limit: int = 10,
        similarity_threshold: float = 0.0
    ) -> List[Dict]:
        """
        Semantic search using vector embeddings.
        
        Args:
            query_text: Natural language query
            entity_type: Optional filter by entity type
            limit: Maximum number of results
            similarity_threshold: Minimum cosine similarity (0.0 to 1.0)
            
        Returns:
            List of entity dictionaries with similarity scores
        """
        # Request vector from DMR
        query_vector = self._get_embedding(query_text)
        
        with self.driver.session() as session:
            # Use vector index query for Neo4j
            if entity_type:
                cypher_query = """
                CALL db.index.vector.queryNodes('entity_embedding_idx', $top_k, $query_vector)
                YIELD node, score
                WHERE node.type = $entity_type AND score >= $threshold
                WITH node as e, score as similarity
                RETURN e.id as id, e.title as title, e.type as type,
                       e.description as description, e.frequency as frequency,
                       e.degree as degree, similarity
                ORDER BY similarity DESC
                LIMIT $limit
                """
                # Use a higher top_k to ensure we get enough results after filtering
                top_k = max(limit * 3, 50)
                result = session.run(
                    cypher_query, 
                    query_vector=query_vector, 
                    entity_type=entity_type,
                    threshold=similarity_threshold,
                    top_k=top_k,
                    limit=limit
                )
            else:
                cypher_query = """
                CALL db.index.vector.queryNodes('entity_embedding_idx', $top_k, $query_vector)
                YIELD node, score
                WHERE score >= $threshold
                WITH node as e, score as similarity
                RETURN e.id as id, e.title as title, e.type as type,
                       e.description as description, e.frequency as frequency,
                       e.degree as degree, similarity
                ORDER BY similarity DESC
                LIMIT $limit
                """
                # Use a higher top_k to ensure we get enough results
                top_k = max(limit * 3, 50)
                result = session.run(
                    cypher_query, 
                    query_vector=query_vector,
                    threshold=similarity_threshold,
                    top_k=top_k,
                    limit=limit
                )
            
            return [dict(record) for record in result]
    
    def get_entity_by_id(self, entity_id: str) -> Optional[Dict]:
        """Get a specific entity by its ID."""
        with self.driver.session() as session:
            query = """
            MATCH (e:Entity {id: $entity_id})
            RETURN e.id as id, e.title as title, e.type as type,
                   e.description as description, e.frequency as frequency,
                   e.degree as degree, e.human_readable_id as human_readable_id
            """
            result = session.run(query, entity_id=entity_id)
            record = result.single()
            return dict(record) if record else None
    
    def get_entity_relationships(
        self, 
        entity_id: Optional[str] = None,
        entity_title: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get all relationships for an entity.
        
        Args:
            entity_id: Entity ID (optional)
            entity_title: Entity title (optional)
            limit: Maximum number of relationships
            
        Returns:
            List of relationship dictionaries
        """
        with self.driver.session() as session:
            if entity_id:
                query = """
                MATCH (a:Entity {id: $entity_id})-[r:RELATED]-(b:Entity)
                RETURN a.title as source_title, a.id as source_id,
                       b.title as target_title, b.id as target_id,
                       r.kind as kind, r.weight as weight, r.description as description,
                       r.id as rel_id, r.combined_degree as combined_degree
                LIMIT $limit
                """
                result = session.run(query, entity_id=entity_id, limit=limit)
            elif entity_title:
                query = """
                MATCH (a:Entity {title: $entity_title})-[r:RELATED]-(b:Entity)
                RETURN a.title as source_title, a.id as source_id,
                       b.title as target_title, b.id as target_id,
                       r.kind as kind, r.weight as weight, r.description as description,
                       r.id as rel_id, r.combined_degree as combined_degree
                LIMIT $limit
                """
                result = session.run(query, entity_title=entity_title, limit=limit)
            else:
                return []
            
            return [dict(record) for record in result]
    
    def find_related_entities(
        self,
        entity_id: Optional[str] = None,
        entity_title: Optional[str] = None,
        max_hops: int = 2,
        limit: int = 20
    ) -> List[Dict]:
        """
        Find entities related to a given entity within N hops.
        
        Args:
            entity_id: Starting entity ID
            entity_title: Starting entity title (used if entity_id not provided)
            max_hops: Maximum number of relationship hops (max 10 for performance)
            limit: Maximum number of results
            
        Returns:
            List of related entities with path information
        """
        # Limit max_hops for performance
        max_hops = min(max_hops, 10)
        
        with self.driver.session() as session:
            if entity_id:
                # Build query with literal max_hops value
                cypher_query = f"""
                MATCH path = (start:Entity {{id: $entity_id}})-[:RELATED*1..{max_hops}]-(related:Entity)
                WHERE start <> related
                WITH related, length(path) as hops, path
                RETURN DISTINCT related.id as id, related.title as title, 
                       related.type as type, related.description as description,
                       hops, count(*) as connection_count
                ORDER BY hops, connection_count DESC
                LIMIT $limit
                """
                result = session.run(cypher_query, entity_id=entity_id, limit=limit)
            elif entity_title:
                # Build query with literal max_hops value
                cypher_query = f"""
                MATCH path = (start:Entity {{title: $entity_title}})-[:RELATED*1..{max_hops}]-(related:Entity)
                WHERE start <> related
                WITH related, length(path) as hops, path
                RETURN DISTINCT related.id as id, related.title as title, 
                       related.type as type, related.description as description,
                       hops, count(*) as connection_count
                ORDER BY hops, connection_count DESC
                LIMIT $limit
                """
                result = session.run(cypher_query, entity_title=entity_title, limit=limit)
            else:
                return []
            
            return [dict(record) for record in result]
    
    def get_entities_by_type(self, entity_type: str, limit: int = 100) -> List[Dict]:
        """Get all entities of a specific type."""
        with self.driver.session() as session:
            query = """
            MATCH (e:Entity {type: $entity_type})
            RETURN e.id as id, e.title as title, e.type as type,
                   e.description as description, e.frequency as frequency,
                   e.degree as degree
            ORDER BY e.frequency DESC, e.degree DESC
            LIMIT $limit
            """
            result = session.run(query, entity_type=entity_type, limit=limit)
            return [dict(record) for record in result]
    
    def get_graph_stats(self) -> Dict:
        """Get statistics about the knowledge graph."""
        with self.driver.session() as session:
            queries = {
                "total_entities": "MATCH (e:Entity) RETURN count(e) as count",
                "total_relationships": "MATCH ()-[r:RELATED]->() RETURN count(r) as count",
                "entity_types": """
                    MATCH (e:Entity)
                    RETURN e.type as type, count(*) as count
                    ORDER BY count DESC
                """,
                "top_entities_by_degree": """
                    MATCH (e:Entity)
                    WHERE e.degree IS NOT NULL
                    RETURN e.title as title, e.type as type, e.degree as degree
                    ORDER BY e.degree DESC
                    LIMIT 10
                """
            }
            
            stats = {}
            for key, query in queries.items():
                result = session.run(query)
                if key in ["entity_types", "top_entities_by_degree"]:
                    stats[key] = [dict(record) for record in result]
                else:
                    stats[key] = result.single()["count"]
            
            return stats
    
    def search_relationships_by_description(
        self,
        query_text: str,
        limit: int = 20
    ) -> List[Dict]:
        """Search relationships by description text."""
        with self.driver.session() as session:
            cypher_query = """
            MATCH (a:Entity)-[r:RELATED]->(b:Entity)
            WHERE toLower(r.description) CONTAINS toLower($search_text)
            RETURN a.title as source_title, a.id as source_id,
                   b.title as target_title, b.id as target_id,
                   r.kind as kind, r.weight as weight, r.description as description,
                   r.id as rel_id
            ORDER BY r.weight DESC
            LIMIT $limit
            """
            result = session.run(cypher_query, search_text=query_text, limit=limit)
            return [dict(record) for record in result]


class CommandGenerator:
    """Generate shell commands from natural language using Docker Model Runner and Neo4j graph."""
    def __init__(self, graph: Neo4jGraphQuery, llm_url: str = None, model: str = "ai/qwen3:4B-UD-Q8_K_XL"):
        self.graph = graph
        raw_url = llm_url or os.getenv("LLM_URL", "http://model-runner.docker.internal:12434/engines/v1")
        parsed = urlparse(raw_url.rstrip("/"))
        host = parsed.netloc.split(":")[0] if parsed.netloc else "model-runner.docker.internal"
        port = parsed.port or int(os.getenv("MODEL_RUNNER_PORT", "12434"))
        self.llm_base = f"{parsed.scheme}://{host}:{port}/engines/v1"
        self.model = model or os.getenv("LLM_MODEL")
    
    def gather_graph_context(self, user_query: str) -> Dict:
        """
        Gather relevant context from the graph database based on user query.
        first we get semantic search results, then we get the relationships for the top commands, then text search for anything missed. 
        Returns:
            Dictionary with commands, options, relationships, and examples
        """
        context = {
            "commands": [],
            "options": [],
            "relationships": [],
            "examples": []
        }
        
        # Semantic search for relevant entities
        semantic_results = self.graph.semantic_search(
            user_query,
            limit=5,
            similarity_threshold=0.3
        )
        for result in semantic_results:
            if result['type'] == 'COMMAND':
                context['commands'].append({
                    'title': result['title'],
                    'description': result['description']
                })
            elif result['type'] == 'OPTION':
                context['options'].append({
                    'title': result['title'],
                    'description': result['description']
                })
        # Relationships for top 2 commands only, 3 per command (reduces context needed)
        for cmd in context['commands'][:2]:
            rels = self.graph.get_entity_relationships(entity_title=cmd['title'], limit=3)
            for rel in rels:
                context['relationships'].append({
                    'command': rel['source_title'],
                    'option': rel['target_title'],
                    'description': rel.get('description', ''),
                    'weight': rel.get('weight', 1.0)
                })
        # Text search for a few more commands
        text_results = self.graph.search_entities_by_text(user_query, limit=3)
        for result in text_results:
            if result['type'] == 'COMMAND' and not any(c['title'] == result['title'] for c in context['commands']):
                context['commands'].append({
                    'title': result['title'],
                    'description': result['description']
                })
        
        return context
    
    def build_prompt(
        self,
        user_query: str,
        context: Dict,
        shell_context: Optional[Dict] = None,
        recent_history: Optional[list] = None,
    ) -> str:
        """Build the prompt for the model with graph context, optional shell context, and optional recent history."""
        _trunc = lambda s, n: (s[:n] + "…") if s and len(s) > n else (s or "")
        commands_text = ""
        if context['commands']:
            commands_text = "Available Commands:\n"
            for cmd in context['commands'][:3]:
                desc = _trunc(cmd.get('description') or "", 80)
                commands_text += f"  - {cmd['title']}: {desc}\n"
        relationships_text = ""
        if context['relationships']:
            relationships_text = "\nCommand-Option Relationships:\n"
            for rel in context['relationships'][:4]:
                desc = _trunc(rel.get('description') or "", 60)
                relationships_text += f"  - {rel['command']} with {rel['option']}: {desc}\n"
        shell_section = ""
        if shell_context:
            shell_section = f"""
Current working directory: {shell_context.get('cwd', '')}
Directory contents (ls -la):
{shell_context.get('listing', '')}
"""
        history_section = ""
        if recent_history:
            from command_history import format_for_prompt
            history_section = "\n" + format_for_prompt(recent_history) + "\n"
        prompt = f"""You are a helpful assistant that generates shell commands based on user requests.
The command will run in a real terminal. You are given the current directory and its contents so you can refer to existing files and paths.
{shell_section}
{history_section}
{commands_text}
{relationships_text}

User Request: {user_query}

Instructions:
1. Use the current directory and listing above when relevant (e.g. to create files in the right place, or reference existing files).
2. Analyze the user's request and identify the appropriate command.
3. Select the correct options/flags based on the relationships provided.
4. Generate ONLY one complete command on a single line. No here-documents (<< EOF) unless you close them in the same command; prefer simpler alternatives (e.g. grep -v "pattern" file to filter and show, or sed -i to edit in place).
5. When the user wants to see or list something (e.g. "show the grocery list without X"), the command must print the result to stdout so they see it (e.g. grep -v "watermelon" groceries.txt).
6. Use lowercase for commands (e.g., 'ls' not 'LS').
7. Do not include explanations, just the command.
8. When the user refers to past actions (e.g. "that folder", "the file we made", "the same place"), use the Recent actions above to resolve paths and context.
9. You MUST choose the main command only from the Available Commands list above. Do not invent new commands.
10. You MUST use only options/flags that appear in the Command-Option Relationships above for that command. Do not invent new flags.
11. If no safe graph-grounded command exists for this request, output exactly: # UNSUPPORTED: no safe graph-grounded command available

Command:"""
        return prompt
    
    def generate_command(
        self,
        user_query: str,
        shell_context: Optional[Dict] = None,
        recent_history: Optional[list] = None,
        use_graph: bool = True,
    ) -> str:
        """Generate command using Docker Model Runner API."""
        from collections import defaultdict

        if use_graph:
            print(f"\nGathering context from knowledge graph...")
            context = self.gather_graph_context(user_query)
            if not context['commands']:
                return "# UNSUPPORTED: no commands available in knowledge graph for this request"
            print(f"   Found {len(context['commands'])} relevant commands")
        else:
            context = {"commands": [], "options": [], "relationships": [], "examples": []}
        prompt = self.build_prompt(
            user_query, context,
            shell_context=shell_context,
            recent_history=recent_history,
        )
        
        endpoint = f"{self.llm_base}/chat/completions"
        
        # dmr uses openai format
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a shell command generator. Return ONLY the raw command string."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,  # Lower for shell command precision
            "stream": False
        }
        
        print(f"Generating command with Model Runner ({self.model})...")
        try:
            response = requests.post(endpoint, json=payload, timeout=120)
            response.raise_for_status()
            
            result = response.json()
            command = result['choices'][0]['message']['content'].strip()
            
            # Basic cleanup for markdown blocks
            if "```" in command:
                command = command.split("```")[1]
                if command.startswith("bash") or command.startswith("sh"):
                    command = command[4:].strip()
                command = command.split("```")[0].strip()
            # Only keep the first line
            command = command.split('\n')[0].strip()

            # If graph grounding is enabled, validate the command against the graph context
            if use_graph:
                #refusal case
                if command.startswith("# UNSUPPORTED"):
                    return command

                tokens = command.split()
                if not tokens:
                    return "# UNSUPPORTED: empty command"

                # Normalize the command name to lowercase for comparison and output
                raw_cmd_name = tokens[0]
                cmd_name = raw_cmd_name.lower()
                flags = [t for t in tokens[1:] if t.startswith("-")]

                # case insensitive lookup
                allowed_cmds_lower = {c["title"].lower() for c in context["commands"]}
                if cmd_name not in allowed_cmds_lower:
                    return "# UNSUPPORTED: command not grounded in knowledge graph"

                #mapping the command to flags
                allowed_flags_for_cmd = defaultdict(set)
                for rel in context["relationships"]:
                    cmd_key = (rel["command"] or "").lower()
                    if cmd_key:
                        allowed_flags_for_cmd[cmd_key].add(rel["option"])

                bad_flags = [
                    f for f in flags
                    if f not in allowed_flags_for_cmd.get(cmd_name, set())
                ]
                if bad_flags:
                    return "# UNSUPPORTED: flags not grounded in knowledge graph"

                # Rebuild the command string with a lowercase command name for execution
                command = " ".join([cmd_name] + tokens[1:])

            return command
            
        except Exception as e:
            return f"# Error calling Model Runner: {e}"


def main():
    import sys
    
    print("Desktop Agent - Command Generator")
    print("Using Neo4j knowledge graph + Docker Model Runner for command generation")
    
    with Neo4jGraphQuery() as graph:
        # Display graph statistics
        stats = graph.get_graph_stats()
        print(f"\nKnowledge Graph: {stats['total_entities']} entities, {stats['total_relationships']} relationships")
        
        # Initialize command generator
        generator = CommandGenerator(graph, model=os.getenv("LLM_MODEL"))

        try:
            response = requests.get(f"{generator.llm_base}/models", timeout=5)
            if response.status_code == 200: #Success
                data = response.json().get("data", [])
                # Get model IDs from the OpenAI-style response
                model_names = [m.get("id", "") for m in data]
                target = generator.model
                match = next((m for m in model_names if m == target or m.endswith("/" + target) or target in m), None)
                if match:
                    generator.model = match
                elif model_names:
                    generator.model = model_names[0]
                print(f"Model Runner connected, using: {generator.model}")
            else:
                print(f"Model Runner API returned status {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Could not connect to Model Runner at {generator.llm_base}")
            print(f"Error: {e}")
            return
        from agent import run_interactive_agent
        run_interactive_agent(generator)


if __name__ == "__main__":
    main()
