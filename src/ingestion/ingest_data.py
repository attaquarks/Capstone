"""
Lab 2: Knowledge Engineering & Domain Grounding
Ingestion script for Supply Chain Intelligence Agent.

This script processes project-specific files (CSV, TXT) from data/,
cleans domain-specific noise, enriches chunks with metadata, applies semantic chunking,
embeds them using Google Generative AI embeddings, and indexes them in ChromaDB.
"""

import os
import csv
import re
import uuid
from datetime import datetime
from typing import Any

import chromadb
from chromadb.config import Settings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

from src.paths import DATA_DIR, CHROMA_DIR, ensure_runtime_dirs

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COLLECTION_NAME = "supply_chain_knowledge"
ensure_runtime_dirs()


def clean_text(text: str) -> str:
    """Strip domain-specific noise: extra whitespace, HTML tags, headers/footers."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"={3,}", "", text)
    text = re.sub(r"-{3,}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()
    return text


def parse_csv_to_documents(filepath: str, doc_type: str) -> list[dict[str, Any]]:
    """Parse a CSV file into structured document chunks with metadata."""
    documents = []
    filename = os.path.basename(filepath)

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for i, row in enumerate(rows):
        row_text_parts = []
        for key, value in row.items():
            if value:
                row_text_parts.append(f"{key}: {value}")
        row_text = "; ".join(row_text_parts)
        cleaned = clean_text(row_text)

        # Determine priority level based on content
        priority = "normal"
        if doc_type == "inventory":
            try:
                current = int(row.get("current_stock", 0))
                reorder = int(row.get("reorder_point", 0))
                if current <= reorder:
                    priority = "critical"
                elif current <= reorder * 1.5:
                    priority = "high"
            except (ValueError, TypeError):
                pass
        elif doc_type == "supplier":
            try:
                score = float(row.get("reliability_score", 1.0))
                if score < 0.85:
                    priority = "high"
            except (ValueError, TypeError):
                pass

        # Determine department
        department = "procurement"
        if doc_type == "logistics":
            department = "logistics"
        elif doc_type == "inventory":
            department = "warehouse"

        doc = {
            "text": cleaned,
            "metadata": {
                "doc_type": doc_type,
                "department": department,
                "priority_level": priority,
                "source_file": filename,
                "row_index": i,
                "last_updated": datetime.now().isoformat(),
            },
        }
        documents.append(doc)

    return documents


def parse_text_to_documents(filepath: str, doc_type: str) -> list[dict[str, Any]]:
    """Parse a text file into semantically chunked documents with metadata."""
    documents = []
    filename = os.path.basename(filepath)

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    cleaned = clean_text(content)

    # Use semantic chunking: split by product sections
    if "PRODUCT:" in cleaned:
        sections = re.split(r"(?=PRODUCT:)", cleaned)
    else:
        # Fallback to recursive character splitting
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", " "],
        )
        sections = splitter.split_text(cleaned)

    for i, section in enumerate(sections):
        section = section.strip()
        if not section or len(section) < 20:
            continue

        # Extract product ID if present
        product_match = re.search(r"\(PRD-\d+\)", section)
        product_id = product_match.group(0).strip("()") if product_match else "general"

        priority = "normal"
        if "critical" in section.lower() or "safety" in section.lower():
            priority = "high"

        doc = {
            "text": section,
            "metadata": {
                "doc_type": doc_type,
                "department": "engineering",
                "priority_level": priority,
                "source_file": filename,
                "chunk_index": i,
                "product_id": product_id,
                "last_updated": datetime.now().isoformat(),
            },
        }
        documents.append(doc)

    return documents


def ingest_all_data() -> list[dict[str, Any]]:
    """Process all files in the data/ directory."""
    all_documents = []

    file_type_map = {
        "inventory_report.csv": ("csv", "inventory"),
        "supplier_catalog.csv": ("csv", "supplier"),
        "logistics_data.csv": ("csv", "logistics"),
        "procurement_history.csv": ("csv", "procurement"),
        "product_specifications.txt": ("txt", "product_specs"),
    }

    for filename, (file_type, doc_type) in file_type_map.items():
        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"  [SKIP] {filename} not found")
            continue

        print(f"  [PROCESS] {filename} as {doc_type}...")
        if file_type == "csv":
            docs = parse_csv_to_documents(str(filepath), doc_type)
        else:
            docs = parse_text_to_documents(str(filepath), doc_type)

        all_documents.extend(docs)
        print(f"    -> {len(docs)} chunks extracted")

    return all_documents


def embed_and_index(documents: list[dict[str, Any]]) -> chromadb.Collection:
    """Embed documents using Google Generative AI and index in ChromaDB."""
    print("\n[EMBEDDING] Initializing Google Generative AI embeddings...")
    embeddings_model = GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-001",
        google_api_key=GEMINI_API_KEY,
    )

    print("[INDEXING] Setting up ChromaDB...")
    chroma_host = os.getenv("CHROMA_HOST")
    if chroma_host:
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        print(f"  Using remote ChromaDB at http://{chroma_host}:{chroma_port}")
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    else:
        print(f"  Using local PersistentClient at {CHROMA_DIR}")
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Delete existing collection if it exists
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Supply Chain Intelligence Knowledge Base"},
    )

    EMBED_DIM = 768  # embedding-001 outputs 768-dimensional vectors

    # Process in batches to respect API limits
    batch_size = 20
    for i in range(0, len(documents), batch_size):
        batch = list(documents)[i : i + batch_size]
        texts = [doc["text"] for doc in batch]
        metadatas = [doc["metadata"] for doc in batch]
        ids = [str(uuid.uuid4()) for _ in batch]

        print(f"  [BATCH] Embedding documents {i+1}-{i+len(batch)} of {len(documents)}...")
        try:
            vectors = embeddings_model.embed_documents(texts)
            collection.add(
                documents=texts,
                embeddings=vectors,
                metadatas=metadatas,
                ids=ids,
            )
        except Exception as e:
            print(f"  [ERROR] Failed to embed batch: {e}")
            # Fallback: zero-vectors preserve correct dimension so ChromaDB stays consistent
            fallback_vectors = [[0.0] * EMBED_DIM for _ in texts]
            collection.add(
                documents=texts,
                embeddings=fallback_vectors,
                metadatas=metadatas,
                ids=ids,
            )

    print(f"\n[DONE] Indexed {collection.count()} documents in collection '{COLLECTION_NAME}'")
    return collection


def test_retrieval(collection: chromadb.Collection):
    """Run test queries to verify the knowledge base."""
    print("\n" + "=" * 60)
    print("RETRIEVAL TESTS")
    print("=" * 60)

    embeddings_model = GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-001",
        google_api_key=GEMINI_API_KEY,
    )

    def embed_query(text: str) -> list:
        try:
            return embeddings_model.embed_query(text)
        except Exception as e:
            print(f"  [WARN] Could not embed query: {e}")
            return [0.0] * 768

    # Test 1: General query
    print("\n--- Test 1: General inventory query ---")
    results = collection.query(
        query_embeddings=[embed_query("What is the current stock level of hydraulic pumps?")],
        n_results=3,
    )
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        print(f"  [{meta.get('doc_type')}] {doc[:100]}...")

    # Test 2: Metadata filtering - only supplier documents
    print("\n--- Test 2: Metadata filtering (supplier docs only) ---")
    results = collection.query(
        query_embeddings=[embed_query("Which supplier has the best reliability score?")],
        n_results=3,
        where={"doc_type": "supplier"},
    )
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        print(f"  [{meta.get('doc_type')} | {meta.get('priority_level')}] {doc[:100]}...")

    # Test 3: Priority-based filtering
    print("\n--- Test 3: Critical priority items ---")
    results = collection.query(
        query_embeddings=[embed_query("Items that need immediate reorder")],
        n_results=3,
        where={"priority_level": "critical"},
    )
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        print(f"  [{meta.get('doc_type')} | CRITICAL] {doc[:100]}...")


if __name__ == "__main__":
    print("=" * 60)
    print("Supply Chain Intelligence - Data Ingestion Pipeline")
    print("=" * 60)

    print("\n[STEP 1] Ingesting and cleaning data...")
    documents = ingest_all_data()
    print(f"\nTotal documents prepared: {len(documents)}")

    print("\n[STEP 2] Embedding and indexing in ChromaDB...")
    collection = embed_and_index(documents)

    print("\n[STEP 3] Running retrieval tests...")
    test_retrieval(collection)

    print("\n[COMPLETE] Knowledge base is ready.")
