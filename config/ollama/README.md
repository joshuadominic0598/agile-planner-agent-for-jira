# Optional local model configuration

[Product tour](../../README.md) · [Model connection setup](../../docs/jira_agent.md) · [Context and memory](../../docs/conversations.md)

The Modelfiles provide optional local chat models. `make start` does not install Ollama or download weights.

| File | Model family |
| --- | --- |
| [nemotron-cascade-8b.Modelfile](nemotron-cascade-8b.Modelfile) | NVIDIA Nemotron Cascade 8B · community Q4_K_M quantization |
| [qwen3-8b.Modelfile](qwen3-8b.Modelfile) | Qwen3 8B |
| [qwen3-14b.Modelfile](qwen3-14b.Modelfile) | Qwen3 14B |

Follow the [local model instructions](../../docs/jira_agent.md) to create the configured models, expose a reachable OpenAI-compatible endpoint and add them to the app. Switching the chat model does not require rebuilding the ticket index; changing the embedding model does.

Declare context windows that match the actual serving configuration. Choosing an expanded conversation profile does not increase the model server’s capacity. Larger models and windows need more memory and can respond more slowly.

Environment templates are in [.env.example](../../.env.example). Keep real credentials in local configuration and out of Git.

## Add Nemotron 8B

Start Ollama, then run from the repository root:

```sh
sh scripts/setup-nemotron.sh
```

This downloads approximately 5 GB and creates `agileplanner-nemotron-cascade:8b`, with a 32,768-token serving window, temperature 0.6 and top-p 0.95. Downloads can resume after interruption. Choose **Sprint Agent → Configure → Set up Nemotron 8B**, save, and **Test selected connection** before chatting. Existing Qwen connections remain available. The Docker preset reaches Ollama through `host.docker.internal`; native Python development uses `127.0.0.1`.

The model is [NVIDIA Nemotron-Cascade-8B](https://huggingface.co/nvidia/Nemotron-Cascade-8B), using [Bartowski’s community GGUF quantization](https://huggingface.co/bartowski/nvidia_Nemotron-Cascade-8B-GGUF). NVIDIA reports reasoning and tool-use evaluations; these do not establish which model is best for your Jira questions. The original context window is 32K; this configuration does not enable YaRN extension. Use the model’s NVIDIA Open Model License terms. Reranking and final synthesis use the selected connection; no separate Qwen model is required.
