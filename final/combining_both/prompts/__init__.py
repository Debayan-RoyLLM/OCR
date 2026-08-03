"""Everything the models are told, one file per thing they are asked.

The pipeline makes three different calls, and each has its own file here:

    judge.py      CALL 1  is this page worth reading at all?   -> JUDGE_PROMPT
    schema.py     CALL 2  the contract the answer must fit     -> SCHEMA
    header.py     CALL 3  what to call the CSV columns         -> HEADER_SCHEMA
                                                                  header_prompt()

The extraction call's instructions are long enough to be worth splitting by what
they read off the page, and PROMPT is those three parts joined in order:

    page.py       STEP 1-2   what kind of page, and its event/division/date
    standings.py  STEP 3-4   where each boxer FINISHED   -> `standings`
    bracket.py    STEP 5     who boxed WHOM              -> `bouts`

To change how brackets are read, edit bracket.py and nothing else. Importers see
the same names as before — `from prompts import PROMPT, SCHEMA, ...` is unchanged.
"""
from prompts.bracket import BRACKET_STEPS
from prompts.header import HEADER_PROMPT, HEADER_SCHEMA, header_prompt
from prompts.judge import JUDGE_PROMPT
from prompts.page import PAGE_STEPS
from prompts.schema import SCHEMA
from prompts.standings import STANDINGS_STEPS

# One blank line between the parts, exactly as when they lived in one file.
PROMPT = "\n".join([PAGE_STEPS, STANDINGS_STEPS, BRACKET_STEPS])

__all__ = ["SCHEMA", "PROMPT", "JUDGE_PROMPT", "HEADER_SCHEMA", "HEADER_PROMPT",
           "header_prompt", "PAGE_STEPS", "STANDINGS_STEPS", "BRACKET_STEPS"]
