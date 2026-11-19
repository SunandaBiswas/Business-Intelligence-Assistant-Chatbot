"""Suggested questions for the Ask pop-up, chosen by register type."""

GENERIC = [
    "How many rows are in this register?",
    "Show a sample of 20 rows",
]

BY_CATEGORY = {
    "Collection": [
        "Total premium by year",
        "Top 10 branches by premium",
        "Premium by class of business",
        "New vs existing business premium",
        "Premium by distribution channel",
        "Monthly premium for the latest year",
    ],
    "Renewal": [
        "How many policies are due for renewal by year?",
        "Renewal premium by branch (top 10)",
        "Breakdown by renewal status",
        "Premium by class of business",
    ],
    "Claims": [
        "Total amount paid by loss year",
        "Top 10 branches by claim payments",
        "Claims by nature of loss",
        "The 10 largest claims",
    ],
    "Targets & campaigns": [
        "Total by year",
        "Breakdown by distribution channel",
        "Top 10 branches",
        "Monthly trend for the latest year",
    ],
    "Bancassurance": [
        "Premium by month",
        "Top 10 branches by premium",
        "Breakdown by class of business",
    ],
    "Reference lists": [
        "List all branch names",
        "List all classes of business",
    ],
}

ALL_REGISTERS = [
    "Total premium collected by year",
    "Top 10 branches by claim payments",
    "Target by distribution channel for 2025",
    "Monthly premium collected in 2025",
]


def suggestions_for(category=None):
    """Suggested questions: type-specific ones first, then the generic two.
    category=None means 'All registers'."""
    if category is None:
        return ALL_REGISTERS
    return BY_CATEGORY.get(category, []) + GENERIC
