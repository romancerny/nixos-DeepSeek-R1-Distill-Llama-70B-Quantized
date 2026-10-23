Build a dependency-free Python 3 subscription billing simulator with a command-line interface and thorough unit tests.

Requirements:
- Represent customers, plans, subscription periods, proration, churn, and variable VAT rates for at least three EU countries.
- Keep monetary calculations exact with `decimal.Decimal`; never use binary floats for persisted money.
- Provide a documented module API and a CLI that reads a JSON scenario from a file and writes a JSON invoice/report to stdout.
- Validate malformed input, missing rates, cancelled subscriptions, period boundaries, leap years, and negative or excessive tax rates.
- Separate source files from `tests/` so independent coding and QA agents have disjoint ownership.
- Use only the Python standard library and make `python -m unittest discover -s tests -v` pass.
- Include a concise `README.md` in the generated workspace with a runnable example and an explanation of rounding/proration rules.

The acceptance review must check the actual numerical outputs and edge cases, not only whether files exist.
