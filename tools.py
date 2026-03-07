"""
Lab 3: The Reasoning Loop - Tool Engineering
Supply Chain Intelligence Agent Tools with Pydantic validation and @tool decorators.

Each tool interacts with the "External World" (Vector DB, CSV data, calculations)
to provide the agent with real-time supply chain intelligence.
"""

import os
import csv
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
import chromadb
from dotenv import load_dotenv

load_dotenv()

# --- Data paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "Initial_Data")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_db")
COLLECTION_NAME = "supply_chain_knowledge"


# --- Helper: Load CSV data ---
def _load_csv(filename: str) -> list[dict]:
    """Load a CSV file from the Initial_Data directory."""
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- Pydantic Input Schemas ---

class InventoryQueryInput(BaseModel):
    """Input schema for querying inventory levels."""
    product_id: Optional[str] = Field(None, description="Product ID (e.g., 'PRD-001'). If not provided, returns all products.")
    product_name: Optional[str] = Field(None, description="Product name or partial name to search for.")


class RiskScoreInput(BaseModel):
    """Input schema for calculating reorder risk score."""
    product_id: str = Field(..., description="Product ID to calculate risk for (e.g., 'PRD-001').")


class SupplierSearchInput(BaseModel):
    """Input schema for searching supplier information."""
    query: str = Field(..., description="Natural language query about suppliers (e.g., 'reliable bearing suppliers').")
    country: Optional[str] = Field(None, description="Filter by supplier country.")


class EmailGenerationInput(BaseModel):
    """Input schema for generating procurement emails."""
    supplier_name: str = Field(..., description="Name of the supplier to address the email to.")
    product_name: str = Field(..., description="Product being procured.")
    quantity: int = Field(..., description="Quantity to order.", gt=0)
    urgency: str = Field("normal", description="Urgency level: 'normal', 'high', or 'critical'.")


class ProductSpecsInput(BaseModel):
    """Input schema for retrieving product specifications."""
    product_id: str = Field(..., description="Product ID to look up (e.g., 'PRD-001').")


# --- Tool Definitions ---

@tool(args_schema=InventoryQueryInput)
def query_inventory(product_id: Optional[str] = None, product_name: Optional[str] = None) -> str:
    """Query current inventory stock levels for products. Returns product details
    including current stock, reorder point, unit cost, and supplier information.
    Use this tool when the user asks about stock levels, inventory status, or product availability."""
    rows = _load_csv("inventory_report.csv")
    if not rows:
        return "Error: Inventory data not available."

    results = []
    for row in rows:
        if product_id and row.get("product_id", "").upper() == product_id.upper():
            results.append(row)
        elif product_name and product_name.lower() in row.get("product_name", "").lower():
            results.append(row)
        elif not product_id and not product_name:
            results.append(row)

    if not results:
        return f"No inventory records found for product_id='{product_id}' or product_name='{product_name}'."

    output_lines = []
    for r in results:
        stock = int(r.get("current_stock", 0))
        reorder = int(r.get("reorder_point", 0))
        status = "CRITICAL - Below Reorder Point" if stock <= reorder else "OK"
        output_lines.append(
            f"Product: {r['product_name']} ({r['product_id']})\n"
            f"  Category: {r.get('category', 'N/A')}\n"
            f"  Current Stock: {stock} | Reorder Point: {reorder} | Max Stock: {r.get('max_stock', 'N/A')}\n"
            f"  Unit Cost: ${r.get('unit_cost', 'N/A')} | Lead Time: {r.get('lead_time_days', 'N/A')} days\n"
            f"  Supplier: {r.get('supplier_id', 'N/A')} | Status: {status}"
        )

    return "\n\n".join(output_lines)


@tool(args_schema=RiskScoreInput)
def calculate_risk_score(product_id: str) -> str:
    """Calculate the reorder risk score for a specific product based on current stock,
    reorder point, lead time, and supplier reliability. Returns a risk level (Critical/High/Medium/Low)
    with a numeric score (0-100). Use this when the user asks about reorder risk or procurement urgency."""
    inventory = _load_csv("inventory_report.csv")
    suppliers = _load_csv("supplier_catalog.csv")

    product = None
    for row in inventory:
        if row.get("product_id", "").upper() == product_id.upper():
            product = row
            break

    if not product:
        return f"Error: Product '{product_id}' not found in inventory."

    supplier_id = product.get("supplier_id", "")
    supplier = None
    for s in suppliers:
        if s.get("supplier_id", "") == supplier_id:
            supplier = s
            break

    current_stock = int(product.get("current_stock", 0))
    reorder_point = int(product.get("reorder_point", 0))
    max_stock = int(product.get("max_stock", 1))
    lead_time = int(product.get("lead_time_days", 0))
    reliability = float(supplier.get("reliability_score", 0.5)) if supplier else 0.5

    # Risk calculation formula
    stock_ratio = current_stock / max_stock if max_stock > 0 else 0
    below_reorder = max(0, (reorder_point - current_stock) / reorder_point) if reorder_point > 0 else 0
    lead_time_factor = min(lead_time / 45.0, 1.0)  # Normalize to 45 days max
    reliability_penalty = 1.0 - reliability

    risk_score = (
        below_reorder * 40 +          # 40% weight: stock vs reorder
        (1 - stock_ratio) * 25 +       # 25% weight: stock vs max
        lead_time_factor * 20 +        # 20% weight: lead time
        reliability_penalty * 15       # 15% weight: supplier reliability
    )
    risk_score = min(100, max(0, risk_score))

    if risk_score >= 70:
        level = "CRITICAL"
    elif risk_score >= 50:
        level = "HIGH"
    elif risk_score >= 30:
        level = "MEDIUM"
    else:
        level = "LOW"

    supplier_name = supplier.get("supplier_name", "Unknown") if supplier else "Unknown"

    return (
        f"Risk Assessment for {product['product_name']} ({product_id}):\n"
        f"  Risk Score: {risk_score:.1f}/100 | Level: {level}\n"
        f"  Current Stock: {current_stock} | Reorder Point: {reorder_point}\n"
        f"  Lead Time: {lead_time} days | Supplier: {supplier_name} (Reliability: {reliability:.0%})\n"
        f"  Recommendation: {'IMMEDIATE REORDER REQUIRED' if level in ('CRITICAL', 'HIGH') else 'Monitor regularly'}\n"
        f"  Suggested Order Qty: {max(0, max_stock - current_stock)} units to reach max stock"
    )


@tool(args_schema=SupplierSearchInput)
def search_suppliers(query: str, country: Optional[str] = None) -> str:
    """Search the knowledge base for supplier information using semantic search.
    Can filter by country. Use this when the user asks about suppliers, pricing, or vendor options."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)

        where_filter = {"doc_type": "supplier"}
        if country:
            where_filter = {"$and": [{"doc_type": "supplier"}, {"department": "procurement"}]}

        results = collection.query(
            query_texts=[query],
            n_results=5,
            where=where_filter,
        )

        if not results["documents"][0]:
            return "No supplier information found for your query."

        output_lines = ["Supplier Search Results:"]
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            output_lines.append(f"\n  Source: {meta.get('source_file', 'N/A')} | Priority: {meta.get('priority_level', 'N/A')}")
            output_lines.append(f"  {doc[:300]}")

        return "\n".join(output_lines)

    except Exception as e:
        # Fallback to CSV if ChromaDB not available
        suppliers = _load_csv("supplier_catalog.csv")
        results = []
        for s in suppliers:
            if (query.lower() in str(s).lower() or
                (country and country.lower() in s.get("country", "").lower())):
                results.append(s)

        if not results:
            return "No matching suppliers found."

        output_lines = ["Supplier Search Results (from catalog):"]
        for s in results[:5]:
            output_lines.append(
                f"\n  {s['supplier_name']} ({s['supplier_id']}) - {s['country']}\n"
                f"    Specialization: {s.get('specialization', 'N/A')}\n"
                f"    Reliability: {s.get('reliability_score', 'N/A')} | Min Order: ${s.get('min_order_value', 'N/A')}\n"
                f"    Contact: {s.get('contact_email', 'N/A')} | Terms: {s.get('payment_terms', 'N/A')}"
            )
        return "\n".join(output_lines)


@tool(args_schema=EmailGenerationInput)
def generate_procurement_email(supplier_name: str, product_name: str, quantity: int, urgency: str = "normal") -> str:
    """Generate a professional procurement email or RFQ (Request for Quote) for a supplier.
    Use this tool when the user needs to draft supplier communications or purchase orders."""
    urgency_text = {
        "critical": "We require EXPEDITED processing due to critical stock levels.",
        "high": "We would appreciate priority handling of this order.",
        "normal": "Standard processing timeline is acceptable.",
    }

    email = f"""
PROCUREMENT EMAIL DRAFT
========================
To: {supplier_name}
Subject: Request for Quote - {product_name} (Qty: {quantity})

Dear {supplier_name} Sales Team,

I hope this message finds you well. We are writing to request a formal
quotation for the following item:

  Product: {product_name}
  Quantity: {quantity} units
  Delivery: To our main warehouse facility

{urgency_text.get(urgency, urgency_text['normal'])}

Please include the following in your quotation:
  1. Unit price and total cost
  2. Available quantity and lead time
  3. Shipping method and estimated delivery date
  4. Any applicable volume discounts
  5. Payment terms

We value our ongoing partnership and look forward to your prompt response.

Best regards,
Supply Chain Management Team
    """.strip()

    return email


@tool(args_schema=ProductSpecsInput)
def get_product_specs(product_id: str) -> str:
    """Retrieve detailed technical specifications for a product from the knowledge base.
    Use this when the user needs technical details, dimensions, or application information."""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)

        results = collection.query(
            query_texts=[f"Product specifications for {product_id}"],
            n_results=3,
            where={"doc_type": "product_specs"},
        )

        if results["documents"][0]:
            return f"Product Specifications for {product_id}:\n\n" + "\n\n".join(results["documents"][0])
        else:
            return f"No specifications found for product {product_id}."

    except Exception:
        # Fallback: read from text file
        specs_path = os.path.join(DATA_DIR, "product_specifications.txt")
        if os.path.exists(specs_path):
            with open(specs_path, "r") as f:
                content = f.read()
            # Find the section for this product
            import re
            pattern = rf"PRODUCT:.*?{product_id}.*?(?=PRODUCT:|$)"
            match = re.search(pattern, content, re.DOTALL)
            if match:
                return f"Product Specifications:\n{match.group(0).strip()}"
        return f"No specifications found for product {product_id}."


# List of all tools for use in graph construction
ALL_TOOLS = [
    query_inventory,
    calculate_risk_score,
    search_suppliers,
    generate_procurement_email,
    get_product_specs,
]
