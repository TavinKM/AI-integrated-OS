#!/bin/bash
# Pre-pull models for Docker Model Runner so compose runs reuse the cache

set -e
echo "Pulling models for Docker Model Runner..."
echo ""

echo "Pulling LLM: ai/qwen3:4B-UD-Q8_K_XL"
docker model pull ai/qwen3:4B-UD-Q8_K_XL

echo ""
echo "Pulling embedding model: hf.co/Mungert/all-MiniLM-L6-v2-GGUF:q8_0"
docker model pull hf.co/Mungert/all-MiniLM-L6-v2-GGUF:q8_0

echo ""
echo "Done. Models are cached. Compose connects to DMR directly (no model provisioning on each run)."
