#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
command -v ollama >/dev/null 2>&1 || { echo 'Install and start Ollama first: https://ollama.com'; exit 1; }
ollama create agileplanner-nemotron-cascade:8b -f config/ollama/nemotron-cascade-8b.Modelfile
echo 'Nemotron installed. In Sprint Agent → Configure, open Model connections, choose Use Nemotron 8B, and test tool calling.'
