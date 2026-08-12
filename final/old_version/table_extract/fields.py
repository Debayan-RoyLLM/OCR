"""The vocabulary of value shapes a column can have.

Each entry is (regex fragment, converter). Add one only if your table holds a
shape not already listed — then use its key in config.COLUMNS.
"""

FIELD = {
    "int":         (r"(\d+)",      int),        # 12
    "num":         (r"([0-9.]+)",  float),      # 56.25
    "upper3":      (r"([A-Z]{3})", str),        # IND
    "upper2":      (r"([A-Z]{2})", str),        # IN
    "code_or_int": (r"([x\d]+)",   str),        # 12 or x
    "word":        (r"(\S+)",      str),        # one token, no spaces
    "text":        (r"(.+?)",      str.strip),  # free text — at most one column
}
