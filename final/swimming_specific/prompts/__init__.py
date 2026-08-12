"""Everything the models are told, one file per thing they are asked.

The pipeline makes three different calls, and each has its own file here:

    judge.py      CALL 1  is this page worth reading at all?   -> JUDGE_PROMPT
    schema.py     CALL 2  the contract the answer must fit     -> SCHEMA
    header.py     CALL 3  what to call the CSV columns         -> HEADER_SCHEMA
                                                                  header_prompt()

The extraction call's instructions are long enough to be worth splitting by what
they read off the page, and PROMPT is those three parts joined in order:

    page.py       STEP 1-2   what kind of page, and each block's heading
    results.py    STEP 3     where each swimmer FINISHED   -> `results`
    relay.py      STEP 4     who swam which leg            -> `relay_legs`

The step numbers are global but the files are local, so THIS TABLE is the one
place that says who owns what. Add a step by taking the next number in your own
file's range and widening it here; do not renumber across files.
"""
from prompts.header import HEADER_PROMPT, HEADER_SCHEMA, header_prompt
from prompts.judge import JUDGE_PROMPT
from prompts.page import PAGE_STEPS
from prompts.relay import RELAY_STEPS
from prompts.results import RESULTS_STEPS
from prompts.schema import SCHEMA

PROMPT = "\n".join([PAGE_STEPS, RESULTS_STEPS, RELAY_STEPS])

__all__ = ["SCHEMA", "PROMPT", "JUDGE_PROMPT", "HEADER_SCHEMA", "HEADER_PROMPT",
           "header_prompt", "PAGE_STEPS", "RESULTS_STEPS", "RELAY_STEPS"]
