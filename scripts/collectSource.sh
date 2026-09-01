#!/bin/bash

# =====================================================
# Mac Script: Ubuntu CLI Dataset Collector (Curated)
# =====================================================
# Requirements: wget, lynx
# Install if missing: brew install wget lynx
# =====================================================

# ---------------------------
# 1. Base directories
# ---------------------------
BASE_DIR="./ubuntu_cli_dataset"
MAN_DIR="$BASE_DIR/manpages"
GNU_DIR="$BASE_DIR/gnu_manuals"
CHUNK_DIR="$BASE_DIR/chunks"

mkdir -p "$MAN_DIR" "$GNU_DIR" "$CHUNK_DIR"

echo "Dataset base directory: $BASE_DIR"

# ---------------------------
# 2. Curated list of important Ubuntu commands
# ---------------------------
COMMANDS=(
ls cp mv rm mkdir rmdir touch cat less head tail find grep sed awk cut sort uniq wc chmod chown ps top kill tar gzip gunzip df du mount umount ping ssh scp curl wget
apt dpkg systemctl journalctl service useradd usermod groupadd passwd cron crontab ip ifconfig netstat ufw
gcc g++ make cmake git docker kubectl pip python3 node npm
)

# ---------------------------
# 3. Download curated Ubuntu man pages
# ---------------------------
echo "[1/4] Downloading curated Ubuntu manpages..."
for cmd in "${COMMANDS[@]}"; do
    URL="https://manpages.ubuntu.com/manpages/focal/en/man1/${cmd}.1.html"
    OUTPUT="$MAN_DIR/${cmd}.html"
    
    wget -q -O "$OUTPUT" "$URL"
    
    # Convert to plain text
    TXT_OUTPUT="${OUTPUT%.html}.txt"
    lynx -dump -nolist "$OUTPUT" > "$TXT_OUTPUT"
done
echo "Downloaded and converted ${#COMMANDS[@]} manpages."

# ---------------------------
# 4. Download GNU Manuals
# ---------------------------
echo "[2/4] Downloading GNU Coreutils and Bash manuals..."

# Coreutils
COREUTILS_URL="https://www.gnu.org/software/coreutils/manual/coreutils.html"
wget -q -O "$GNU_DIR/coreutils.html" "$COREUTILS_URL"
lynx -dump -nolist "$GNU_DIR/coreutils.html" > "$GNU_DIR/coreutils.txt"

# Bash
BASH_URL="https://www.gnu.org/software/bash/manual/bash.html"
wget -q -O "$GNU_DIR/bash.html" "$BASH_URL"
lynx -dump -nolist "$GNU_DIR/bash.html" > "$GNU_DIR/bash.txt"

echo "GNU manuals downloaded and converted."

# ---------------------------
# 5. Chunk large text files for GraphRAG
# ---------------------------
echo "[3/4] Chunking text files for GraphRAG ingestion..."

CHUNK_SIZE=1000  # lines per chunk
for TXT_FILE in $(find "$MAN_DIR" "$GNU_DIR" -name "*.txt"); do
    FILE_BASE=$(basename "$TXT_FILE" .txt)
    split -l $CHUNK_SIZE "$TXT_FILE" "$CHUNK_DIR/${FILE_BASE}_chunk_"
done

echo "Chunking complete. Chunks stored in $CHUNK_DIR"

# ---------------------------
# 6. Cleanup
# ---------------------------
echo "[4/4] Cleanup: removing HTML files..."
find "$MAN_DIR" "$GNU_DIR" -name "*.html" -delete

echo "Dataset ready for GraphRAG ingestion!"
echo "Directory structure:"
echo "  - $MAN_DIR : curated manpages (HTML removed)"
echo "  - $GNU_DIR : GNU manuals (HTML removed)"
echo "  - $CHUNK_DIR : chunked text files ready for extraction"