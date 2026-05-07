import sys
import os
import asyncio
from contextlib import asynccontextmanager
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import httpx
import secrets
import hashlib
import base64
from dotenv import load_dotenv
from fastapi import FastAPI,HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict
from backend.config import (
    HUBSPOT_ACCESS_TOKEN,HUBSPOT_BASE_URL,HUBSPOT_MCP_MODE,
    HUBSPOT_MCP_BASE_URL,HUBSPOT_CLIENT_ID,HUBSPOT_CLIENT_SECRET,
    HUBSPOT_REDIRECT_URI,HUBSPOT_MCP_ACCESS_TOKEN,HUBSPOT_MCP_REFRESH_TOKEN,
)

_ENV_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
)
load_dotenv(_ENV_PATH, override=True)

HUBSPOT_MCP_MODE          = HUBSPOT_MCP_MODE
HUBSPOT_MCP_BASE          = HUBSPOT_MCP_BASE_URL
HUBSPOT_CLIENT_ID         = HUBSPOT_CLIENT_ID
HUBSPOT_CLIENT_SECRET     = HUBSPOT_CLIENT_SECRET
HUBSPOT_REDIRECT_URI      = HUBSPOT_REDIRECT_URI
_token_store = {
    "access_token":  HUBSPOT_MCP_ACCESS_TOKEN,
    "refresh_token": HUBSPOT_MCP_REFRESH_TOKEN,
}

_refresh_lock = None

_pkce_store: Dict[str, str] = {}

from contextlib import asynccontextmanager
import asyncio

async def auto_refresh_loop():
    """Refresh token every 25 minutes automatically."""
    while True:
        await asyncio.sleep(25 * 60)
        print("Scheduled token refresh...")
        await _do_refresh()

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(auto_refresh_loop())
    yield

mcp_app = FastAPI(title="Own MCP Server (+ HubSpot Beta MCP Bridge)", lifespan=lifespan)

mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HUBSPOT_TOKEN = HUBSPOT_ACCESS_TOKEN

TOOLS: Dict[str, dict] = {
    "hubspot_get_contacts": {
        "description": "Fetch recent HubSpot CRM contacts",
        "provider": "hubspot",
        "params": ["limit"],
    },
    "hubspot_create_contact": {
        "description": "Create a new HubSpot contact",
        "provider": "hubspot",
        "params": ["email", "firstname", "lastname"],
    },
    "hubspot_get_deals": {
        "description": "List open HubSpot deals",
        "provider": "hubspot",
        "params": ["limit"],
    },
    "hubspot_get_companies": {
        "description": "Fetch HubSpot companies",
        "provider": "hubspot",
        "params": ["limit"],
    },
    "hubspot_get_tickets": {
        "description": "Fetch HubSpot support tickets",
        "provider": "hubspot",
        "params": ["limit"],
    },
    "hubspot_mcp_call": {
        "description": "Call ANY tool on HubSpot's official beta remote MCP server.",
        "provider": "hubspot_mcp_beta",
        "params": ["tool_name", "tool_params"],
    },
    "hubspot_mcp_list_tools": {
        "description": "List all tools on HubSpot's official beta remote MCP server.",
        "provider": "hubspot_mcp_beta",
        "params": [],
    },
    "hubspot_create_deal": {
        "description": "Create a new HubSpot deal",
        "provider": "hubspot",
        "params": ["dealname", "amount"],
    },
    "hubspot_update_contact": {
        "description": "Update a HubSpot contact by its ID",
        "provider": "hubspot",
        "params": ["contact_id", "email", "firstname", "lastname"],
    },
    "hubspot_delete_contact": {
        "description": "Delete a HubSpot contact by its ID",
        "provider": "hubspot",
        "params": ["contact_id"],
    },
    "hubspot_update_deal": {
        "description": "Update a HubSpot deal by its ID",
        "provider": "hubspot",
        "params": ["deal_id", "dealname", "amount"],
    },
    "hubspot_delete_deal": {
        "description": "Delete a HubSpot deal by its ID",
        "provider": "hubspot",
        "params": ["deal_id"],
    },
    "hubspot_create_company": {
        "description": "Create a new HubSpot company",
        "provider": "hubspot",
        "params": ["name", "domain"],
    },
    "hubspot_update_company": {
        "description": "Update a HubSpot company by its ID",
        "provider": "hubspot",
        "params": ["company_id", "name", "domain"],
    },
    "hubspot_delete_company": {
        "description": "Delete a HubSpot company by its ID",
        "provider": "hubspot",
        "params": ["company_id"],
    },
    "hubspot_create_ticket": {
        "description": "Create a new HubSpot ticket",
        "provider": "hubspot",
        "params": ["subject", "content"],
    },
    "hubspot_update_ticket": {
        "description": "Update a HubSpot ticket by its ID",
        "provider": "hubspot",
        "params": ["ticket_id", "subject", "content"],
    },
    "hubspot_delete_ticket": {
        "description": "Delete a HubSpot ticket by its ID",
        "provider": "hubspot",
        "params": ["ticket_id"],
    },
    "echo": {
        "description": "Echo back a message (built-in test tool)",
        "provider": "builtin",
        "params": ["message"],
    },
    "web_search_mcp": {
        "description": "Search the web via MCP layer",
        "provider": "builtin",
        "params": ["query"],
    },
}

HUBSPOT_BASE = HUBSPOT_BASE_URL

async def hs_get_contacts(limit: int = 5) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts/search",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={
                "limit": limit,
                "properties": ["firstname", "lastname", "email"],
                "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}]
            },
            timeout=10,
        )
        return r.json()


async def hs_create_contact(email: str, firstname: str = "", lastname: str = "") -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts",
            headers={
                "Authorization": f"Bearer {HUBSPOT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"properties": {"email": email, "firstname": firstname, "lastname": lastname}},
            timeout=10,
        )
        return r.json()

async def hs_update_contact(contact_id: str, email: str = "", firstname: str = "", lastname: str = "") -> dict:
    props = {k: v for k, v in {"email": email, "firstname": firstname, "lastname": lastname}.items() if v}
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": props},
            timeout=10,
        )
        return r.json()


async def hs_delete_contact(contact_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            timeout=10,
        )
        return {"status": r.status_code, "deleted": r.status_code == 204}


async def hs_get_deals(limit: int = 5) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            params={"limit": limit, "properties": "dealname,amount,dealstage"},
            timeout=10,
        )
        return r.json()

async def hs_create_deal(dealname: str, amount: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals",
            headers={
                "Authorization": f"Bearer {HUBSPOT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"properties": {"dealname": dealname, "amount": amount, "dealstage": "appointmentscheduled"}},
            timeout=10,
        )
        return r.json()

async def hs_update_deal(deal_id: str, dealname: str = "", amount: str = "") -> dict:
    props = {k: v for k, v in {"dealname": dealname, "amount": amount}.items() if v}
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": props},
            timeout=10,
        )
        return r.json()


async def hs_delete_deal(deal_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            timeout=10,
        )
        return {"status": r.status_code, "deleted": r.status_code == 204}

async def hs_get_companies(limit: int = 5) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            params={"limit": limit, "properties": "name,domain,industry"},
            timeout=10,
        )
        return r.json()


async def hs_create_company(name: str, domain: str = "") -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": {"name": name, "domain": domain}}, timeout=10
        )
        return r.json()

async def hs_update_company(company_id: str, name: str = "", domain: str = "") -> dict:
    props = {k: v for k, v in {"name": name, "domain": domain}.items() if v}
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/{company_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": props},
            timeout=10,
        )
        return r.json()


async def hs_delete_company(company_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/{company_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            timeout=10,
        )
        return {"status": r.status_code, "deleted": r.status_code == 204}

async def hs_get_tickets(limit: int = 5) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/tickets",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            params={"limit": limit, "properties": "subject,hs_pipeline_stage,content"},
            timeout=10,
        )
        return r.json()

async def hs_create_ticket(subject: str, content: str = "") -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/tickets",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": {"subject": subject, "content": content, "hs_pipeline_stage": "1"}}, timeout=10
        )
        return r.json()

async def hs_update_ticket(ticket_id: str, subject: str = "", content: str = "") -> dict:
    props = {k: v for k, v in {"subject": subject, "content": content}.items() if v}
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{HUBSPOT_BASE}/crm/v3/objects/tickets/{ticket_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"},
            json={"properties": props},
            timeout=10,
        )
        return r.json()


async def hs_delete_ticket(ticket_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            f"{HUBSPOT_BASE}/crm/v3/objects/tickets/{ticket_id}",
            headers={"Authorization": f"Bearer {HUBSPOT_TOKEN}"},
            timeout=10,
        )
        return {"status": r.status_code, "deleted": r.status_code == 204}


async def auto_refresh_loop():
    """Refresh token every 25 min — prevents 401 during active use."""
    while True:
        await asyncio.sleep(25 * 60)
        print("Scheduled token refresh...")
        await _do_refresh()


@asynccontextmanager
async def lifespan(app):
    token   = _token_store.get("access_token", "")
    refresh = _token_store.get("refresh_token", "")
    print(f".env loaded from: {_ENV_PATH}")
    print(f"Access token: {'loaded' if token else 'NOT SET'}")
    if HUBSPOT_MCP_MODE == "beta" and refresh:
        asyncio.create_task(auto_refresh_loop())
        print("Auto token refresh loop started (every 25 min)")
    yield

mcp_app.router.lifespan_context = lifespan

def find_env_path() -> str:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    primary = os.path.normpath(os.path.join(this_dir, "..", ".env"))
    if os.path.exists(primary):
        return primary
    current = this_dir
    for _ in range(5):
        candidate = os.path.join(current, ".env")
        if os.path.exists(candidate):
            return candidate
        current = os.path.dirname(current)
    return primary

def save_tokens_to_env(access_token: str, refresh_token: str):
    """
    Write updated tokens back to the .env file so they persist after restart.
    Searches up the directory tree to find the .env file.
    """
    try:
        env_path = find_env_path()
        print(f"Using .env at: {env_path}")

        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()

        new_lines = []
        access_written  = False
        refresh_written = False

        for line in lines:
            if line.startswith("HUBSPOT_MCP_ACCESS_TOKEN="):
                new_lines.append(f"HUBSPOT_MCP_ACCESS_TOKEN={access_token}\n")
                access_written = True
            elif line.startswith("HUBSPOT_MCP_REFRESH_TOKEN="):
                new_lines.append(f"HUBSPOT_MCP_REFRESH_TOKEN={refresh_token}\n")
                refresh_written = True
            else:
                new_lines.append(line)

        if not access_written:
            new_lines.append(f"HUBSPOT_MCP_ACCESS_TOKEN={access_token}\n")
        if not refresh_written:
            new_lines.append(f"HUBSPOT_MCP_REFRESH_TOKEN={refresh_token}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)

        print(f"Tokens saved to .env automatically.")

    except Exception as e:
        print(f"Could not write to .env: {e} — tokens saved in memory only.")

async def _do_refresh() -> bool:
    """
    Silently refresh the beta MCP access token.
    Uses an asyncio lock to prevent multiple simultaneous refreshes
    (HubSpot refresh tokens are single-use — parallel calls would invalidate each other).
    """
    global _refresh_lock

    if _refresh_lock is None:
        import asyncio
        _refresh_lock = asyncio.Lock()

    if _refresh_lock.locked():
        print("Refresh already in progress — waiting...")
        async with _refresh_lock:
            pass  # just wait for the other refresh to finish
        return True  # token was refreshed by the other caller

    async with _refresh_lock:
        refresh_token = _token_store.get("refresh_token", "")
        if not refresh_token or not HUBSPOT_CLIENT_ID or not HUBSPOT_CLIENT_SECRET:
            return False

        token_url = "https://api.hubapi.com/oauth/v1/token"
        data = {
            "grant_type":    "refresh_token",
            "client_id":     HUBSPOT_CLIENT_ID,
            "client_secret": HUBSPOT_CLIENT_SECRET,
            "refresh_token": refresh_token,
        }
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(token_url, data=data, timeout=10)
                tokens = r.json()

            if "access_token" in tokens:
                new_access  = tokens["access_token"]
                new_refresh = tokens.get("refresh_token", refresh_token)

                _token_store["access_token"]  = new_access
                _token_store["refresh_token"] = new_refresh

                save_tokens_to_env(new_access, new_refresh)

                print("Beta MCP token auto-refreshed successfully.")
                return True
            else:
                print(f"Refresh response missing access_token: {tokens}")
        except Exception as e:
            print(f"Auto token refresh failed: {e}")
        return False

def beta_headers() -> dict:
    token = _token_store.get("access_token", "")
    if not token:
        raise HTTPException(
            status_code=401,
            detail=(
                "HUBSPOT_MCP_ACCESS_TOKEN is not set. "
                "Complete the OAuth PKCE flow via GET /oauth/start first."
            ),
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def beta_post(payload: dict) -> dict:
    """
    Core POST to HubSpot MCP server.
    Handles 401 auto-refresh + retry, and HTML error responses safely.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{HUBSPOT_MCP_BASE}/",
            headers=beta_headers(),
            json=payload,
            timeout=15,
        )

    if r.status_code == 401:
        print("Beta MCP token expired — attempting auto refresh...")
        refreshed = await _do_refresh()
        if not refreshed:
            return {"error": "Token expired and auto-refresh failed. Run /oauth/refresh manually."}
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{HUBSPOT_MCP_BASE}/",
                headers=beta_headers(),
                json=payload,
                timeout=15,
            )

    if not r.is_success:
        return {"error": f"HubSpot MCP error {r.status_code}", "detail": r.text[:200]}

    content_type = r.headers.get("content-type", "")
    if "application/json" in content_type or "text/plain" in content_type:
        try:
            return r.json()
        except Exception:
            return {"error": "Invalid JSON response", "raw": r.text[:200]}

    return {"error": f"Unexpected content-type: {content_type}", "raw": r.text[:200]}


async def beta_list_tools() -> dict:
    return await beta_post({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})


async def beta_call_tool(tool_name: str, tool_params: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name":      tool_name,
            "arguments": tool_params,
        },
    }
    return await beta_post(payload)

def generate_pkce_pair():
    code_verifier  = secrets.token_urlsafe(64)
    digest         = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


@mcp_app.get("/oauth/start")
async def oauth_start():
    if not HUBSPOT_CLIENT_ID:
        raise HTTPException(400, "HUBSPOT_CLIENT_ID not configured in .env")

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    _pkce_store[state] = code_verifier

    auth_url = (
        "https://app.hubspot.com/oauth/authorize"
        f"?client_id={HUBSPOT_CLIENT_ID}"
        f"&redirect_uri={HUBSPOT_REDIRECT_URI}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return RedirectResponse(auth_url)


@mcp_app.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    code_verifier = _pkce_store.pop(state, None)
    if not code_verifier:
        raise HTTPException(400, "Invalid or expired OAuth state parameter")

    token_url = "https://api.hubapi.com/oauth/v1/token"
    data = {
        "grant_type":    "authorization_code",
        "client_id":     HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "redirect_uri":  HUBSPOT_REDIRECT_URI,
        "code":          code,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(token_url, data=data, timeout=10)
        tokens = r.json()

    if "access_token" not in tokens:
        return JSONResponse(status_code=400, content={"error": "Token exchange failed", "detail": tokens})

    _token_store["access_token"]  = tokens["access_token"]
    _token_store["refresh_token"] = tokens.get("refresh_token", "")

    return {
        "message":                   "OAuth success! Tokens saved in memory automatically.",
        "HUBSPOT_MCP_ACCESS_TOKEN":  tokens["access_token"],
        "HUBSPOT_MCP_REFRESH_TOKEN": tokens.get("refresh_token", ""),
        "expires_in":                tokens.get("expires_in"),
        "note":                      "Also save these in .env for persistence after server restart.",
    }


@mcp_app.post("/oauth/refresh")
async def oauth_refresh():
    """Manually refresh the token. Also called automatically on 401."""
    success = await _do_refresh()
    if not success:
        raise HTTPException(400, "Refresh failed — check HUBSPOT_MCP_REFRESH_TOKEN, CLIENT_ID, CLIENT_SECRET in .env")

    return {
        "message":                   "Token refreshed and saved in memory automatically.",
        "HUBSPOT_MCP_ACCESS_TOKEN":  _token_store["access_token"],
        "HUBSPOT_MCP_REFRESH_TOKEN": _token_store["refresh_token"],
        "note":                      "Also update these in .env for persistence after server restart.",
    }

@mcp_app.get("/mcp/tools")
async def list_tools():
    return {"tools": TOOLS, "hubspot_mcp_mode": HUBSPOT_MCP_MODE}


class CallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


@mcp_app.post("/mcp/call")
async def call_tool(req: CallRequest):
    tool_name = req.tool
    params    = req.params

    if tool_name not in TOOLS:
        return JSONResponse(status_code=404, content={"error": f"Tool '{tool_name}' not found"})

    tool = TOOLS[tool_name]

    try:
        if tool["provider"] == "builtin":
            if tool_name == "echo":
                return {"result": params.get("message", "")}
            if tool_name == "web_search_mcp":
                return {"result": f"[MCP web search] Results for: {params.get('query', '')}"}

        if tool["provider"] == "hubspot_mcp_beta":
            if HUBSPOT_MCP_MODE != "beta":
                return {"error": "Set HUBSPOT_MCP_MODE=beta in .env to use beta tools."}
            if tool_name == "hubspot_mcp_list_tools":
                return {"result": await beta_list_tools()}
            if tool_name == "hubspot_mcp_call":
                return {"result": await beta_call_tool(
                    params.get("tool_name", ""),
                    params.get("tool_params", {}),
                )}

        if tool["provider"] == "hubspot":
            if not HUBSPOT_TOKEN:
                return {"error": "HUBSPOT_ACCESS_TOKEN not configured"}
            if tool_name == "hubspot_get_contacts":
                return {"result": await hs_get_contacts(int(params.get("limit", 5)))}
            if tool_name == "hubspot_create_contact":
                return {"result": await hs_create_contact(
                    params.get("email", ""),
                    params.get("firstname", ""),
                    params.get("lastname", ""),
                )}
            if tool_name == "hubspot_get_deals":
                return {"result": await hs_get_deals(int(params.get("limit", 5)))}
            if tool_name == "hubspot_get_companies":
                return {"result": await hs_get_companies(int(params.get("limit", 5)))}
            if tool_name == "hubspot_get_tickets":
                return {"result": await hs_get_tickets(int(params.get("limit", 5)))}
            if tool_name == "hubspot_create_deal":
                return {"result": await hs_create_deal(
                    params.get("dealname", "New Deal"),
                    params.get("amount", "0"),
                )}
            if tool_name == "hubspot_create_company":
                return {"result": await hs_create_company(
                    params.get("name", "New Company"),
                    params.get("domain", "")
                )}

            if tool_name == "hubspot_create_ticket":
                return {"result": await hs_create_ticket(
                    params.get("subject", "New Ticket"),
                    params.get("content", "")
                )}

            if tool_name == "hubspot_update_contact":
                return {"result": await hs_update_contact(
                    params.get("contact_id", ""),
                    params.get("email", ""),
                    params.get("firstname", ""),
                    params.get("lastname", ""),
                )}
            if tool_name == "hubspot_delete_contact":
                return {"result": await hs_delete_contact(params.get("contact_id", ""))}

            if tool_name == "hubspot_update_deal":
                return {"result": await hs_update_deal(
                    params.get("deal_id", ""),
                    params.get("dealname", ""),
                    params.get("amount", ""),
                )}
            if tool_name == "hubspot_delete_deal":
                return {"result": await hs_delete_deal(params.get("deal_id", ""))}

            if tool_name == "hubspot_update_company":
                return {"result": await hs_update_company(
                    params.get("company_id", ""),
                    params.get("name", ""),
                    params.get("domain", ""),
                )}
            if tool_name == "hubspot_delete_company":
                return {"result": await hs_delete_company(params.get("company_id", ""))}

            if tool_name == "hubspot_update_ticket":
                return {"result": await hs_update_ticket(
                    params.get("ticket_id", ""),
                    params.get("subject", ""),
                    params.get("content", ""),
                )}
            if tool_name == "hubspot_delete_ticket":
                return {"result": await hs_delete_ticket(params.get("ticket_id", ""))}


    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    return {"error": "Unknown handler"}

@mcp_app.get("/")
async def root():
    return {
        "service":           "Own MCP Dispatcher",
        "hubspot_mcp_mode":  HUBSPOT_MCP_MODE,
        "beta_mcp_endpoint": HUBSPOT_MCP_BASE,
        "token_loaded":      bool(_token_store.get("access_token")),
        "oauth_start":       "/oauth/start   (GET  – opens browser for PKCE flow)",
        "oauth_refresh":     "/oauth/refresh (POST – refresh access token)",
        "tools":             "/mcp/tools     (GET  – list all tools)",
        "call":              "/mcp/call      (POST – invoke a tool)",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp_app, host="0.0.0.0", port=8001)