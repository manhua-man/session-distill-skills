def final_review_block() -> str:
    return (
        "## Final Session Review\n"
        "- **Final user request:** test request\n"
        "- **Final outcome:** completed\n"
        "- **Last turn state:** completed\n"
        "- **Contradictions:** none\n"
        "- **Open items:** none\n"
        "- **Evidence status:** all ANSWERED\n"
        "- **Promotion allowed:** yes\n"
    )


def distilled_note(extra: str = "") -> str:
    return (
        "# Note\n\n"
        f"{final_review_block()}\n"
        "## Promotion Decision\n\n"
        f"No Promotion. chat_history reviewed.\n{extra}"
    )
