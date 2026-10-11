"""Six side-effect-free action stubs. No insurer or payment system is invoked."""

from .decisions import ActionContext, DECISION_ADAPTER, Decision


def dispatch_action(action: str, context: ActionContext, arguments: dict | None = None) -> Decision:
    """Reject unknown names, invalid amounts, missing/extra arguments, and bad context."""
    return DECISION_ADAPTER.validate_python({
        "action": action, "context": context, "arguments": arguments if arguments is not None else {},
    })


def approve_pre_authorization(context: ActionContext) -> Decision:
    return dispatch_action("approve_pre_authorization", context)


def approve_claim_payment(payment_in_dollars: float, context: ActionContext) -> Decision:
    return dispatch_action("approve_claim_payment", context, {"payment_in_dollars": payment_in_dollars})


def deny_claim(context: ActionContext) -> Decision:
    return dispatch_action("deny_claim", context)


def request_missing_documentation(documents: list[str], context: ActionContext) -> Decision:
    return dispatch_action("request_missing_documentation", context, {"documents": documents})


def route_to_senior_reviewer(context: ActionContext) -> Decision:
    return dispatch_action("route_to_senior_reviewer", context)


def route_to_coding_review(context: ActionContext) -> Decision:
    return dispatch_action("route_to_coding_review", context)
