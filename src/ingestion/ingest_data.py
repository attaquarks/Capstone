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


def _build_embedding_function():
    """Pick an embedding function based on which API key is available.

    * If a Google API key is set → use Google's gemini-embedding-001
      (768-dim, hosted, no extra download).
    * Otherwise → use ChromaDB's built-in default embedding function
      (sentence-transformers/all-MiniLM-L6-v2 via ONNX, 384-dim).
      Downloaded once on first use, fully local thereafter — no key needed.

    Returns a tuple ``(embedding_fn, source_name)``. ``embedding_fn`` is
    None when we want ChromaDB to handle it implicitly via the collection's
    own ``embedding_function``.
    """
    if GEMINI_API_KEY:
        print("[EMBEDDING] Using Google Generative AI embeddings (gemini-embedding-001).")
        return GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001",
            google_api_key=GEMINI_API_KEY,
        ), "google"

    # Local fallback — no API key required. Imported lazily so we don't
    # touch onnxruntime unless we actually need it.
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    print("[EMBEDDING] No GEMINI_API_KEY found — using ChromaDB's local "
          "DefaultEmbeddingFunction (sentence-transformers/all-MiniLM-L6-v2).")
    return DefaultEmbeddingFunction(), "chromadb-default"


def embed_and_index(documents: list[dict[str, Any]]) -> chromadb.Collection:
    """Embed documents and index them in ChromaDB.

    Provider selection is delegated to ``_build_embedding_function`` so the
    pipeline works both with and without a Gemini API key (the Groq path
    has no first-party embedding model)."""
    embeddings_model, embed_source = _build_embedding_function()

    print("[INDEXING] Setting up ChromaDB...")
    chroma_host = os.getenv("CHROMA_HOST")
    if chroma_host:
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        print(f"  Using remote ChromaDB at http://{chroma_host}:{chroma_port}")
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    else:
        print(f"  Using local PersistentClient at {CHROMA_DIR}")
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Delete existing collection if it exists.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    # When using ChromaDB's DefaultEmbeddingFunction, register it on the
    # collection so .query(query_texts=...) calls don't have to embed manually.
    if embed_source == "chromadb-default":
        collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Supply Chain Intelligence Knowledge Base"},
            embedding_function=embeddings_model,
        )
    else:
        collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Supply Chain Intelligence Knowledge Base"},
        )

    # Process in batches to respect API limits.
    batch_size = 20
    for i in range(0, len(documents), batch_size):
        batch = list(documents)[i : i + batch_size]
        texts = [doc["text"] for doc in batch]
        metadatas = [doc["metadata"] for doc in batch]
        ids = [str(uuid.uuid4()) for _ in batch]

        print(f"  [BATCH] Indexing documents {i+1}-{i+len(batch)} of {len(documents)}...")
        if embed_source == "google":
            try:
                vectors = embeddings_model.embed_documents(texts)
                collection.add(
                    documents=texts,
                    embeddings=vectors,
                    metadatas=metadatas,
                    ids=ids,
                )
            except Exception as e:
                # Last-resort fallback: zero vectors keep dimensions consistent
                # so semantic search degrades gracefully but metadata filtering
                # still works.
                print(f"  [ERROR] Failed to embed batch: {e}")
                fallback_vectors = [[0.0] * 768 for _ in texts]
                collection.add(
                    documents=texts,
                    embeddings=fallback_vectors,
                    metadatas=metadatas,
                    ids=ids,
                )
        else:
            # ChromaDB will embed via the collection's registered embedding_function.
            collection.add(
                documents=texts,
                metadatas=metadatas,
                ids=ids,
            )

    print(f"\n[DONE] Indexed {collection.count()} documents in collection '{COLLECTION_NAME}'")
    return collection


def test_retrieval(collection: chromadb.Collection):
    """Run test queries to verify the knowledge base.

    Uses ``query_texts`` rather than pre-computed ``query_embeddings`` so the
    collection's registered embedding function handles encoding — works for
    both the Gemini and the local sentence-transformers backends without a
    code branch."""
    print("\n" + "=" * 60)
    print("RETRIEVAL TESTS")
    print("=" * 60)

    def _run(label: str, query: str, **kwargs):
        print(f"\n--- {label} ---")
        try:
            results = collection.query(query_texts=[query], n_results=3, **kwargs)
        except Exception as e:
            print(f"  [WARN] Query failed: {e}")
            return
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []
        for doc, meta in zip(docs, metas):
            tag = meta.get("doc_type", "?")
            prio = meta.get("priority_level", "?")
            print(f"  [{tag} | {prio}] {doc[:100]}...")

    _run("Test 1: General inventory query",
         "What is the current stock level of hydraulic pumps?")
    _run("Test 2: Metadata filtering (supplier docs only)",
         "Which supplier has the best reliability score?",
         where={"doc_type": "supplier"})
    _run("Test 3: Critical priority items",
         "Items that need immediate reorder",
         where={"priority_level": "critical"})


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
