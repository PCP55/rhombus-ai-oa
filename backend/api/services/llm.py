import re
import signal
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

current_file = Path(__file__).resolve()
root_dir = current_file.parents[3]
env_path = root_dir / ".env"

load_dotenv(env_path)


def generate_regex(prompt: str) -> str:
    """
    Takes a natural language description and returns a validated Regex pattern using Gemini.
    """
    # 1. Initialize LLM
    llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0)

    # 2. Prompt Engineering
    template = """
    You are an expert regular expression generator.
    Given the following natural language description, write a Python-compatible regular expression that matches the pattern.

    IMPORTANT RULES:
    - Return ONLY the raw regular expression pattern.
    - Do NOT wrap the output in quotes or markdown blocks (e.g., no ```regex).
    - Do NOT provide any explanations.

    EXAMPLE:
    Description: Find email addresses in the Email column and replace them with 'REDACTED'.
    Regex Pattern: [A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{{2,7}}

    Description: {prompt}

    Regex Pattern:
    """

    prompt_template = PromptTemplate(input_variables=["prompt"], template=template)

    # 3. Create the LangChain pipeline and execute
    chain = prompt_template | llm
    response = chain.invoke({"prompt": prompt})

    # 4. Extract the raw string from the LLM's response
    raw_regex = response.content[0].get("text", "").strip()

    # 5. Validation & Sanitization
    return validate_regex(raw_regex)


class _RegexTimeoutError(Exception):
    """Raised internally when a regex match is taking suspiciously long."""


@contextmanager
def _time_limit(seconds: float):
    """
    Unix wall-clock timeout for a block of code, via SIGALRM. Used to bound
    how long a *single* regex match attempt is allowed to run.

    Only safe to call from the main thread of a process (true for Celery's
    default prefork worker pool, where each task runs in its own process).
    """

    def _handle_timeout(signum, frame):
        raise _RegexTimeoutError()

    previous_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


# Adversarial inputs chosen to trip up the classic catastrophic-backtracking
# shapes (nested/overlapping quantifiers, alternation with ambiguous
# branches) when run against a pattern that is vulnerable to them. A safe
# regex resolves against all of these in milliseconds; an unsafe one blows
# up exponentially well before REDOS_TIMEOUT_SECONDS. Long enough (120
# chars) to also catch polynomial (not just exponential) worst cases that
# might slip through on a very short probe.
#
# Caveat: this validates against Python's `re` engine. The actual
# replacement runs in Spark, i.e. the JVM regex engine (java.util.regex),
# which can have different worst-case behavior for the same pattern. This
# guard meaningfully reduces risk but is not a byte-for-byte guarantee of
# Spark-side safety -- see the README's LLM safety section.
_REDOS_PROBE_STRINGS = (
    "a" * 120,
    "a" * 120 + "!",  # never matches -> forces the engine to exhaust backtracking
    " " * 120,
    "-" * 120 + "x",
    "0" * 120 + ".",
)

REDOS_TIMEOUT_SECONDS = 0.5


def _guard_against_catastrophic_backtracking(pattern: str) -> None:
    """
    Empirically checks whether `pattern` can be driven into catastrophic
    backtracking (ReDoS) by matching it against a handful of adversarial
    strings, each under a hard wall-clock timeout. Raises ValueError if any
    probe doesn't resolve in time.
    """
    compiled = re.compile(pattern)

    for probe in _REDOS_PROBE_STRINGS:
        try:
            with _time_limit(REDOS_TIMEOUT_SECONDS):
                compiled.search(probe)
        except _RegexTimeoutError:
            raise ValueError(
                f"LLM generated a regex pattern that is unsafe to run (catastrophic "
                f"backtracking risk): {pattern}"
            )


def validate_regex(pattern: str) -> str:
    """
    Validates that the provided string is a valid, safe-to-run Python
    regular expression: syntactically correct, and not vulnerable to
    catastrophic backtracking (ReDoS) on adversarial input.
    """
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(
            f"LLM generated an invalid regex pattern: {pattern}. Error: {str(e)}"
        )

    _guard_against_catastrophic_backtracking(pattern)

    return pattern


if __name__ == "__main__":
    generate_regex("Please generate regex pattern for detecting email addresses")
