def envelope(tool: str, summary: str, parsed: object, error: str = "") -> dict:
    """The project's tool-result shape.

    `summary` is what the LLM reads; `parsed` is the structured data behind
    it, kept around for anything that needs it without re-parsing text.
    """
    return {
        "tool": tool,
        "summary": summary,
        "parsed": parsed,
        "error": error[:300],
    }
