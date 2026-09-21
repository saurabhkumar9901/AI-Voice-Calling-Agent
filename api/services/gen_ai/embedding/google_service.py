"""Google Gemini embedding service.

This module provides document processing capabilities using:
- Google's text-embedding-004 for embeddings (768 dimensions padded to 1536)
- Docling for document conversion and chunking
- pgvector for vector similarity search
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from docling.chunking import HybridChunker
from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from loguru import logger
import google.generativeai as genai
from transformers import AutoTokenizer

from api.db.db_client import DBClient
from api.db.models import KnowledgeBaseChunkModel

from .base import BaseEmbeddingService

# Model configuration
DEFAULT_MODEL_ID = "gemini-embedding-001"
EMBEDDING_DIMENSION = 1536  # Target dimension for database storage
NATIVE_DIMENSION = 768      # Google embeddings native dimension

# For chunking, we'll use the same tokenizer as SentenceTransformer
# since OpenAI/Google uses similar tokenization
TOKENIZER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingAPIKeyNotConfiguredError(Exception):
    """Raised when Google API key is not configured for embeddings."""

    def __init__(self):
        super().__init__(
            "Google API key not configured. Please set your API key in "
            "Model Configurations > Embedding to use document processing."
        )


class GoogleEmbeddingService(BaseEmbeddingService):
    """Embedding service using Google Gemini embeddings."""

    def __init__(
        self,
        db_client: DBClient,
        api_key: Optional[str] = None,
        model_id: str = DEFAULT_MODEL_ID,
        max_tokens: int = 512,
    ):
        """Initialize the Google embedding service.

        Args:
            db_client: Database client for storing documents and chunks
            api_key: Google API key. If not provided, the client will not be
                    initialized and operations will fail with a clear error.
            model_id: Google embedding model ID (default: gemini-embedding-001)
            max_tokens: Maximum number of tokens per chunk (default: 512)
        """
        self.db = db_client
        self.model_id = model_id
        self.max_tokens = max_tokens

        self._api_key_configured = bool(api_key)
        if self._api_key_configured:
            genai.configure(api_key=api_key)
            logger.info(f"Google embedding service initialized with model: {model_id}")
        else:
            logger.warning(
                "Google embedding service initialized without API key. "
                "Operations will fail until API key is configured in Model Configurations."
            )

        # Initialize tokenizer for chunking
        logger.info(
            f"Loading tokenizer for chunking: {TOKENIZER_MODEL} with max_tokens={max_tokens}"
        )
        try:
            self.tokenizer = HuggingFaceTokenizer(
                tokenizer=AutoTokenizer.from_pretrained(
                    TOKENIZER_MODEL,
                    local_files_only=True,
                ),
                max_tokens=max_tokens,
            )
            logger.info("Loaded tokenizer from cache")
        except Exception as e:
            logger.warning(f"Tokenizer not in cache, downloading: {e}")
            self.tokenizer = HuggingFaceTokenizer(
                tokenizer=AutoTokenizer.from_pretrained(TOKENIZER_MODEL),
                max_tokens=max_tokens,
            )
            logger.info("Tokenizer downloaded and cached")

        # Initialize chunker
        logger.info(f"Initializing HybridChunker with max_tokens={max_tokens}")
        self.chunker = HybridChunker(tokenizer=self.tokenizer)

        # Initialize document converter
        self.converter = DocumentConverter()

    def get_model_id(self) -> str:
        """Return the model identifier."""
        return self.model_id

    def get_embedding_dimension(self) -> int:
        """Return the target database embedding dimension."""
        return EMBEDDING_DIMENSION

    def _ensure_api_key_configured(self):
        """Check if API key is configured and raise error if not."""
        if not self._api_key_configured:
            raise EmbeddingAPIKeyNotConfiguredError()

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts using Google Gemini API.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (zero-padded to 1536)

        Raises:
            EmbeddingAPIKeyNotConfiguredError: If API key is not configured
        """
        self._ensure_api_key_configured()

        try:
            model_name = self.model_id if self.model_id.startswith("models/") else f"models/{self.model_id}"
            
            # Google GenAI async API call
            result = await genai.embed_content_async(
                model=model_name,
                content=texts,
                task_type="retrieval_document"
            )

            # Extract embeddings from response and zero pad to 1536 dim
            embeddings = []
            values_list = result.get('embedding', [])
            
            for item in values_list:
                # Get the core embedding values
                values = list(item)
                
                # Zero pad from 768 elements to 1536
                if len(values) < EMBEDDING_DIMENSION:
                    values.extend([0.0] * (EMBEDDING_DIMENSION - len(values)))
                elif len(values) > EMBEDDING_DIMENSION:
                    # Defensive truncation just in case
                    values = values[:EMBEDDING_DIMENSION]
                    
                embeddings.append(values)
                
            return embeddings

        except Exception as e:
            logger.error(f"Error generating Google embeddings: {e}")
            raise

    async def embed_query(self, query: str) -> List[float]:
        """Embed a single query text using Google Gemini API.

        Args:
            query: Query text to embed

        Returns:
            Embedding vector zero-padded to 1536 dimensions as list of floats
        """
        self._ensure_api_key_configured()
        
        try:
            model_name = self.model_id if self.model_id.startswith("models/") else f"models/{self.model_id}"
            
            result = await genai.embed_content_async(
                model=model_name,
                content=query,
                task_type="retrieval_query"
            )
            
            # result['embedding'] could be list or list of lists depending on input
            emb_data = result.get('embedding', [])
            if isinstance(emb_data, list) and len(emb_data) > 0 and isinstance(emb_data[0], list):
                values = list(emb_data[0])
            else:
                values = list(emb_data)
                
            if len(values) < EMBEDDING_DIMENSION:
                values.extend([0.0] * (EMBEDDING_DIMENSION - len(values)))
            elif len(values) > EMBEDDING_DIMENSION:
                values = values[:EMBEDDING_DIMENSION]
                
            return values
        except Exception as e:
            logger.error(f"Error generating Google query embedding: {e}")
            raise

    async def search_similar_chunks(
        self,
        query: str,
        organization_id: int,
        limit: int = 5,
        document_uuids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks using vector similarity.

        Args:
            query: Search query text
            organization_id: Organization ID for scoping
            limit: Maximum number of results to return
            document_uuids: Optional list of document UUIDs to filter by

        Returns:
            List of dictionaries with chunk data and similarity scores
        """
        self._ensure_api_key_configured()

        # Generate query embedding automatically padded to 1536
        query_embedding = await self.embed_query(query)

        # Perform vector similarity search
        results = await self.db.search_similar_chunks(
            query_embedding=query_embedding,
            organization_id=organization_id,
            limit=limit,
            document_uuids=document_uuids,
            embedding_model=self.model_id,
        )

        return results

    async def process_document(
        self,
        file_path: str,
        organization_id: int,
        created_by: int,
        custom_metadata: dict = None,
    ):
        """Process a document: convert, chunk, embed, and store in database.

        Args:
            file_path: Path to the document file
            organization_id: Organization ID for scoping
            created_by: User ID who uploaded the document
            custom_metadata: Optional custom metadata dictionary

        Returns:
            The created document record
        """
        try:
            # Extract file metadata
            filename = Path(file_path).name
            file_hash = self.db.compute_file_hash(file_path)
            file_size = os.path.getsize(file_path)
            mime_type = self.db.get_mime_type(file_path)

            # Check if document already exists
            existing_doc = await self.db.get_document_by_hash(
                file_hash, organization_id
            )
            if existing_doc:
                logger.info(f"Document already exists: {filename} (hash: {file_hash})")
                return existing_doc

            # Create document record
            doc_record = await self.db.create_document(
                organization_id=organization_id,
                created_by=created_by,
                filename=filename,
                file_size_bytes=file_size,
                file_hash=file_hash,
                mime_type=mime_type,
                custom_metadata=custom_metadata or {},
            )

            logger.info(f"Processing document with Google Gemini embeddings: {filename}")

            # Update status to processing
            await self.db.update_document_status(doc_record.id, "processing")

            # Step 1: Convert document using docling
            logger.info("Converting document with docling...")
            conversion_result = self.converter.convert(file_path)
            doc = conversion_result.document

            # Store docling metadata
            docling_metadata = {
                "num_pages": len(doc.pages) if hasattr(doc, "pages") else None,
                "document_type": type(doc).__name__,
            }

            # Step 2: Chunk the document
            logger.info(f"Chunking document with max_tokens={self.max_tokens}...")
            chunks = list(self.chunker.chunk(dl_doc=doc))
            total_chunks = len(chunks)

            logger.info(f"Generated {total_chunks} chunks")

            # Step 3: Process each chunk
            chunk_texts = []
            chunk_records = []
            token_counts = []

            for i, chunk in enumerate(chunks):
                chunk_text = chunk.text
                contextualized_text = self.chunker.contextualize(chunk=chunk)

                text_to_tokenize = (
                    contextualized_text if contextualized_text else chunk_text
                )
                token_count = len(
                    self.tokenizer.tokenizer.encode(
                        text_to_tokenize, add_special_tokens=False
                    )
                )
                token_counts.append(token_count)

                # Prepare chunk metadata
                chunk_metadata = {}
                if hasattr(chunk, "meta") and chunk.meta:
                    chunk_metadata = {
                        "doc_items": (
                            [str(item) for item in chunk.meta.doc_items]
                            if hasattr(chunk.meta, "doc_items")
                            else []
                        ),
                        "headings": (
                            chunk.meta.headings
                            if hasattr(chunk.meta, "headings")
                            else []
                        ),
                    }

                # Set Google's model_id and correct embedding dimension
                chunk_record = KnowledgeBaseChunkModel(
                    document_id=doc_record.id,
                    organization_id=organization_id,
                    chunk_text=chunk_text,
                    contextualized_text=contextualized_text,
                    chunk_index=i,
                    chunk_metadata=chunk_metadata,
                    embedding_model=self.model_id,
                    embedding_dimension=EMBEDDING_DIMENSION,
                    token_count=token_count,
                )

                chunk_records.append(chunk_record)
                chunk_texts.append(text_to_tokenize)

            # Log chunk statistics
            if token_counts:
                avg_tokens = sum(token_counts) / len(token_counts)
                min_tokens = min(token_counts)
                max_tokens_stats = max(token_counts)
                logger.info("Chunk token statistics:")
                logger.info(f"  - Average: {avg_tokens:.1f} tokens")
                logger.info(f"  - Min: {min_tokens} tokens")
                logger.info(f"  - Max: {max_tokens_stats} tokens")

            # Step 4: Generate embeddings using Google Gemini API
            # Note: We batch texts because API allows multiple strings.
            # But Gemini API generally respects array inputs up to a token limit.
            logger.info(f"Generating embeddings using Google Gemini ({self.model_id})...")
            
            # Max 100 items per request for most embedded APIs batched
            BATCH_SIZE = 100
            all_embeddings = []
            
            model_name = self.model_id if self.model_id.startswith("models/") else f"models/{self.model_id}"
            
            for i in range(0, len(chunk_texts), BATCH_SIZE):
                batch_texts = chunk_texts[i : i + BATCH_SIZE]
                result = await genai.embed_content_async(
                    model=model_name,
                    content=batch_texts,
                    task_type="retrieval_document"
                )
                
                values_list = result.get('embedding', [])
                for item in values_list:
                    values = list(item)
                    if len(values) < EMBEDDING_DIMENSION:
                        values.extend([0.0] * (EMBEDDING_DIMENSION - len(values)))
                    all_embeddings.append(values)

            # Step 5: Attach embeddings to chunk records
            for chunk_record, embedding in zip(chunk_records, all_embeddings):
                chunk_record.embedding = embedding

            # Step 6: Save all chunks in batch
            logger.info("Storing chunks in database...")
            await self.db.create_chunks_batch(chunk_records)

            # Update document status to completed
            await self.db.update_document_status(
                doc_record.id,
                "completed",
                total_chunks=total_chunks,
                docling_metadata=docling_metadata,
            )

            logger.info(f"Successfully processed document: {filename}")
            logger.info(f"  - Total chunks: {total_chunks}")
            logger.info(f"  - Embedding model: {self.model_id}")

            return doc_record

        except Exception as e:
            logger.error(f"Error processing document with Google Gemini: {e}")

            if "doc_record" in locals():
                await self.db.update_document_status(
                    doc_record.id, "failed", error_message=str(e)
                )

            raise
