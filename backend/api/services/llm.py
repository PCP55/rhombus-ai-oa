import re

from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


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


def validate_regex(pattern: str) -> str:
    """
    Validates that the provided string is a valid Python regular expression.
    """
    try:
        re.compile(pattern)
        return pattern
    except re.error as e:
        raise ValueError(
            f"LLM generated an invalid regex pattern: {pattern}. Error: {str(e)}"
        )
