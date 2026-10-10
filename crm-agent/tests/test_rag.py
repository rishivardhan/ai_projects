from crm_agent.rag.index import load_knowledge_chunks, tokenize


def test_knowledge_chunks_have_sections():
    chunks = load_knowledge_chunks()
    assert len(chunks) >= 20
    assert all(c.text for c in chunks)


def test_tokenize_stems():
    assert tokenize("Discounts and renewals") == ["discount", "renewal"]


def test_policy_retrieval(ctx):
    hits = ctx.retriever.search("who approves a 25% discount", source="knowledge_base")
    assert "Discount authority" in hits[0]["title"]


def test_interaction_retrieval_scoped(ctx, db):
    hits = ctx.retriever.search("data residency encryption keys", source="interactions", top_k=10)
    assert hits and all(h["source"] == "interactions" for h in hits)
    acc = hits[0]["metadata"]["account_id"]
    scoped = ctx.retriever.search("data residency", source="interactions", account_id=acc)
    assert scoped and all(h["metadata"]["account_id"] == acc for h in scoped)
