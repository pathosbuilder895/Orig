"""
validation/diagnostics/ — one-off probes that isolate WHY a benchmark
number looks the way it does, as opposed to validation/wide/ and
validation/verify/, which measure Original's production scoring path
as-is.

Diagnostics are allowed to use ML techniques Original's production
scoring never uses (e.g. a supervised classifier trained directly on
feature vectors) specifically to separate two questions that a
production-path benchmark conflates: "are the FEATURES good?" vs
"is the SCORING METHOD good?"
"""
