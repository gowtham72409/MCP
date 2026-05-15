import numpy as np
from typing import List
from sentence_transformers import SentenceTransformer
from Real_Time_Chatbot.backend.config import EMBEDDING_MODEL,SIMILARITY_THRESHOLD

model=SentenceTransformer(EMBEDDING_MODEL)

def embedd(text:str):
    return model.encode([text])[0]

def cosine_similarity(vec1,vec2):
    a=np.array(vec1)
    b=np.array(vec2)

    return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-9))

def embedd_batch(texts:List[str]):
    return list(model.encode(texts))

def find_similar(query: str, texts: List[str], top_k: int = 3) -> List[dict]:
    """Return the top-k most similar texts with their cosine scores."""
    if not texts:
        return []
    q_vec = embedd(query)
    t_vecs = embedd_batch(texts)
    results = [
        {"text": t, "score": cosine_similarity(q_vec, v), "index": i}
        for i, (t, v) in enumerate(zip(texts, t_vecs))
    ]
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]

def detect_intent(text:str):
      
    intents = {
        "question":     "What is the answer to my question? I need information.",
        "task":         "Please do this task for me and complete the action.",
        "creative":     "Write creative content, generate ideas, brainstorm.",
        "analysis":     "Analyze, evaluate, compare, and provide insights.",
        "code":         "Write code, debug, explain programming concepts.",
        "conversation": "Let's chat and have a conversation.",
    }
    q_vec = embedd(text)
    scores = {k: cosine_similarity(q_vec, embedd(v)) for k, v in intents.items()}
    top = max(scores, key=scores.get)
    return {"primary_intent": top, "scores": scores, "confidence": scores[top]}

class _AysncShim:

    async def embed(self,text:str):
        return embedd(text).tolist()
    
    async def embedd_batch(self,texts:List[str]):
        return [v.tolist() for v in embedd_batch(texts)]
    
    def cosine_similarity(self,a,b):
        return cosine_similarity(a,b)
    
    async def find_similar(self, query: str, texts: List[str], top_k: int = 3):
        return find_similar(query, texts, top_k)
 
    async def detect_intent(self, text: str):
        return detect_intent(text)
    
embedding_services=_AysncShim()