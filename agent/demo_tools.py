"""
demo_tools.py — A small, self-contained procurement toolset for the demo.

Read tools serve fixed content (no network): web pages and a vendor API.
Side-effecting tools (send_email, create_purchase_order) only record what
they would have done, in an Outbox, so a demo run shows whether the agent
was hijacked into acting.
"""

import json
from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool


@dataclass
class Outbox:
    emails: list = field(default_factory=list)
    orders: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def side_effects(self) -> list[str]:
        out = [f"email to {e['to']}: {e['subject']}" for e in self.emails]
        out += [f"purchase order: {o['vendor']} x{o['quantity']}" for o in self.orders]
        return out


def build_tools(pages: dict[str, str], api_records: dict[str, dict], outbox: Outbox) -> list:
    def web_fetch(url: str) -> str:
        """Fetch a web page and return its HTML."""
        return pages.get(url, f"404 Not Found: {url}")

    def vendor_api(vendor_id: str) -> str:
        """Look up a vendor record by id in the procurement API. Returns JSON."""
        rec = api_records.get(vendor_id)
        return json.dumps(rec) if rec else json.dumps({"error": "unknown vendor", "vendor_id": vendor_id})

    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email on the user's behalf."""
        outbox.emails.append({"to": to, "subject": subject, "body": body})
        return f"Email sent to {to}."

    def create_purchase_order(vendor: str, quantity: int) -> str:
        """Create a purchase order with a vendor."""
        outbox.orders.append({"vendor": vendor, "quantity": quantity})
        return f"Purchase order created: {vendor}, quantity {quantity}."

    def write_notes(text: str) -> str:
        """Save the summary to the user's procurement notes."""
        outbox.notes.append(text)
        return "Notes saved."

    return [StructuredTool.from_function(f) for f in
            (web_fetch, vendor_api, send_email, create_purchase_order, write_notes)]
