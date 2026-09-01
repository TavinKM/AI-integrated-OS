FROM ubuntu:22.04

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Add LLVM 20 repository / might not be needed anymore
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    lsb-release \
    && wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add - \
    && echo "deb http://apt.llvm.org/jammy/ llvm-toolchain-jammy-20 main" >> /etc/apt/sources.list.d/llvm.list

# Install ALL required system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    curl \
    build-essential \
    cmake \
    pkg-config \
    llvm-20 \
    llvm-20-dev \
    libffi-dev \
    libedit-dev \
    libzstd-dev \
    zlib1g-dev \
    libxml2-dev \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set LLVM config path
ENV LLVM_CONFIG=/usr/bin/llvm-config-20

# Install uv
RUN pip install uv

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen

COPY main.py startup.py agent.py shell_session.py web_app.py command_history.py README.md ./
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY graphrag/ ./graphrag/
#new entrypoint
CMD ["uv", "run", "python", "startup.py"] 