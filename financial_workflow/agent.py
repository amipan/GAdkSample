import asyncio

from google.adk.agents import Agent

from borrower_agent.agent import (
    extract_pdf_pages,
    invoke_borrower_agent,
    validate_result as validate_borrower_result,
)
from financial_classifier.agent import (
    invoke_financial_classifier,
    resolve_pdf_path,
    validate_classification,
)


async def analyze_financial_pdf_tool(pdf_path: str) -> dict:
    """Run borrower extraction and financial-statement classification on one PDF."""
    resolved_path = resolve_pdf_path(pdf_path)
    pages = extract_pdf_pages(resolved_path)

    borrower_result, classification_result = await asyncio.gather(
        invoke_borrower_agent(resolved_path, pages),
        invoke_financial_classifier(resolved_path, pages),
    )

    return {
        "filename": resolved_path.name,
        "pages_processed": len(pages),
        "borrower": validate_borrower_result(borrower_result, pages),
        "financial_classification": validate_classification(
            classification_result,
            pages,
        ),
    }


root_agent = Agent(
    name="root_agent",
    model="gemini-2.5-flash",
    description="Runs borrower extraction and financial statement classification for one PDF.",
    instruction="""
When the user provides a PDF path and asks to analyze it, call
analyze_financial_pdf_tool. Return both the borrower extraction and the
financial-statement classification from the tool. Do not claim either result
unless the tool returns it.
""",
    tools=[analyze_financial_pdf_tool],
)