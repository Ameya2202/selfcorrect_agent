"""Example target file you can point the agent at to see the cycle work.

`normalize_spaces` only trims the ends — it does NOT collapse internal runs of
whitespace, and it crashes on None. Run the agent on this file and watch it
propose a fix, generate tests, self-correct a faulty test, and ask you to apply.
"""


def normalize_spaces(text):
    """Collapse whitespace in a string."""
    return text.strip()
