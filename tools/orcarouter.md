# OrcaRouter Integration

How Forscher uses OrcaRouter as a secondary LLM provider for complex tasks.

## What is OrcaRouter?

[OrcaRouter](https://www.orcarouter.ai) is an open-source AI router providing access to **160+ models** through a single OpenAI-compatible API endpoint. It intelligently routes requests to the optimal model based on task requirements.

## Setup

### Endpoint
```
https://api.orcarouter.ai/v1
```

### Authentication
API key stored in environment:
```bash
ORCAROUTER_API_KEY=your_key_here
```

### Hermes Configuration
Provider registered as `custom:orcarouter` in Hermes config:
```yaml
provider: custom:orcarouter
base_url: https://api.orcarouter.ai/v1
api_key_env: ORCAROUTER_API_KEY
```

## Available Models (Highlights)

| Model | Provider | Best For |
|-------|----------|----------|
| `anthropic/claude-opus-4.7` | Anthropic | Complex reasoning, code review |
| `openai/gpt-4.5` | OpenAI | General purpose |
| `google/gemini-3.0-pro` | Google | Large context, research |
| `deepseek/deepseek-v4-pro` | DeepSeek | Technical analysis |
| `meta/llama-4-maverick` | Meta | Open-source alternative |
| `xai/grok-4` | xAI | Creative tasks |
| `orcarouter/auto` | Auto-router | Let the router decide |

## Usage Pattern

### Default Provider (Daily Tasks)
```
DeepSeek v4-pro — fast, cheap, sufficient for routine analysis
```

### OrcaRouter (Heavy Tasks)
Switch temporarily for complex operations:

```bash
# Via Hermes CLI
hermes chat --provider custom:orcarouter -m anthropic/claude-opus-4.7

# Return to default
hermes chat --provider deepseek
```

### When to Use OrcaRouter
- Multi-step reasoning tasks
- Complex code generation or review
- Research synthesis across multiple sources
- Tasks where DeepSeek struggles

### When NOT to Use
- Quick market checks
- Simple API calls
- Routine monitoring
- Everything that DeepSeek handles fine

---

*Integrated: 2026-05-24*
