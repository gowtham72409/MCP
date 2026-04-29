import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL= os.getenv("DATABASE_URL")
REDIS_URL= os.getenv("REDIS_URL")
HUBSPOT_ACCESS_TOKEN= os.getenv("HUBSPOT_ACCESS_TOKEN")
MCP_BASE_URL = os.getenv("MCP_BASE_URL")
HUBSPOT_BASE_URL=os.getenv("HUBSPOT_BASE_URL")
EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL")

HUBSPOT_MCP_MODE          = os.getenv("HUBSPOT_MCP_MODE")   
HUBSPOT_MCP_BASE_URL      = os.getenv("HUBSPOT_MCP_BASE_URL")
HUBSPOT_CLIENT_ID         = os.getenv("HUBSPOT_CLIENT_ID")
HUBSPOT_CLIENT_SECRET     = os.getenv("HUBSPOT_CLIENT_SECRET")
HUBSPOT_REDIRECT_URI      = os.getenv("HUBSPOT_REDIRECT_URI")
HUBSPOT_MCP_ACCESS_TOKEN  = os.getenv("HUBSPOT_MCP_ACCESS_TOKEN")
HUBSPOT_MCP_REFRESH_TOKEN = os.getenv("HUBSPOT_MCP_REFRESH_TOKEN")