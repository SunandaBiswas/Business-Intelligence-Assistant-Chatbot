# Knowledge-Based and Machine Learning Applications

## Overview

The HR Assistant includes knowledge-based and machine learning applications, although it does not currently contain a trained predictive or classification model.

The application mainly combines:

- A large language model (LLM) for understanding questions and generating answers
- Retrieval over annual report documents
- SQL-based retrieval from an MIS database
- TF-IDF and cosine similarity for document relevance ranking

## 1. LLM-Based SQL Application

The application uses the Groq LLM API to turn a user's plain-English question into a database query.

The process in `sql_agent.py` is:

1. The LLM reviews the available database tables and selects the one to three most relevant tables.
2. The LLM writes a read-only PostgreSQL `SELECT` or `WITH` query.
3. The query is executed against the Supabase PostgreSQL database.
4. If the SQL query fails, the database error is sent back to the LLM for one automatic correction attempt.
5. The LLM explains the returned rows in clear plain language.

This is an application of generative AI and natural-language processing, using the `openai/gpt-oss-120b` model by default. Groq receives the user's question, table schemas, and limited sample rows, but not the complete database.

## 2. Retrieval-Augmented Knowledge Application

The public chat page includes a retrieval-augmented generation (RAG) style feature for Green Delta Insurance annual reports.

The process in `app_pages/public_chat.py` is:

1. Extract text from local annual report documents.
2. Divide each report into overlapping text chunks.
3. Convert the text chunks into TF-IDF vectors.
4. Convert the user's question into a TF-IDF query vector.
5. Use cosine similarity to rank the most relevant report sections.
6. Send the selected report information and the user's question to the Groq LLM.
7. Return an answer based on the retrieved content.

This application combines information retrieval with a generative language model. The source text is used as supporting knowledge instead of relying only on the LLM's training knowledge.

## 3. Machine Learning Components

The project uses the scikit-learn library for the following machine learning operations:

- `TfidfVectorizer` creates numerical representations of document and query text.
- Cosine similarity measures how closely a question matches a document chunk.
- English stop-word removal and word/word-pair features improve text matching.

This is an unsupervised information-retrieval or document-ranking technique. It does not require supervised model training because the TF-IDF vocabulary is created dynamically from the available report text.

No trained classification, regression, clustering, forecasting, or recommendation model is currently included in the application. Pandas and summary calculations are used for reporting and aggregation, but they are not machine learning models.

## 4.  RAG Experiment

The active RAG-style implementation is in `app_pages/public_chat.py`.

## Conclusion

The HR Assistant is a knowledge-based AI application that uses an LLM for natural-language understanding and SQL generation, and TF-IDF/cosine similarity for document retrieval. Machine learning is used for text similarity and ranking, while traditional supervised or unsupervised predictive model training has not yet taken place.
