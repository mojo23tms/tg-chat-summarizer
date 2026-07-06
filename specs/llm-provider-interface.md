# LLM Provider Interface Specification

The LLM layer should expose provider-neutral behavior.

## Result Shape

A generated result should include:

```text
text
provider
model
usage
estimated
finish_reason
```

## Usage Shape

Usage should support:

```text
input_tokens
output_tokens
total_tokens
```

If provider usage is unavailable, estimate usage and mark it as estimated.

## Provider Responsibilities

Each provider adapter should:

- validate required configuration;
- call the provider API;
- normalize text output;
- normalize usage metadata;
- raise clear provider-specific errors behind common exception types where practical.

## Business Logic Boundary

Command handlers should not import provider SDKs. Provider SDK imports belong inside provider adapters.
