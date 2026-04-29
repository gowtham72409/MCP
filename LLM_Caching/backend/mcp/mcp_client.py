import sys
import os
import re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import httpx
from typing import Any, Dict, Optional
from backend.config import MCP_BASE_URL, HUBSPOT_MCP_MODE

MCP_BASE = MCP_BASE_URL
HUBSPOT_MCP_MODE = HUBSPOT_MCP_MODE

async def list_mcp_tools() -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{MCP_BASE}/mcp/tools", timeout=5)
        return r.json()


async def call_mcp_tool(tool: str, params: Dict[str, Any] = {}) -> Any:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{MCP_BASE}/mcp/call",
            json={"tool": tool, "params": params},
            timeout=10,
        )
        return r.json()


async def resolve_tool(user_input: str) -> Optional[dict]:
    lower = user_input.lower()

    if any(kw in lower for kw in ("hubspot", "crm", "contact", "deal", "company", "ticket", "quote")):

        if HUBSPOT_MCP_MODE == "beta":

            if "create" in lower or "add" in lower:

                if "deal" in lower:
                    return {
                        "tool": "hubspot_mcp_call",
                        "params": {
                            "tool_name": "crm_create_object",
                            "tool_params": {
                                "objectType": "deals",
                                "properties": {
                                    "dealname": extract_value(user_input, "dealname") or extract_value(user_input, "deal") or "New Deal",
                                    "dealstage": "appointmentscheduled",
                                    "amount": extract_value(user_input, "amount"),
                                    "hubspot_owner_id": "YOUR_OWNER_ID",
                                },
                            },
                        },
                    }

                if "company" in lower or "companies" in lower:
                    return {
                        "tool": "hubspot_mcp_call",
                        "params": {
                            "tool_name": "crm_create_object",
                            "tool_params": {
                                "objectType": "companies",
                                "properties": {
                                    "name": extract_value(user_input, "company"),
                                },
                            },
                        },
                    }

                if "ticket" in lower:
                    return {
                        "tool": "hubspot_mcp_call",
                        "params": {
                            "tool_name": "crm_create_object",
                            "tool_params": {
                                "objectType": "tickets",
                                "properties": {
                                    "subject": extract_value(user_input, "ticket"),
                                    "hs_pipeline_stage": "1",
                                },
                            },
                        },
                    }

                return {
                    "tool": "hubspot_mcp_call",
                    "params": {
                        "tool_name": "crm_create_object",
                        "tool_params": {
                            "objectType": "contacts",
                            "properties": {
                                "email":     extract_email(user_input),
                                "firstname": extract_value(user_input, "firstname"),
                                "lastname":  extract_value(user_input, "lastname"),
                            },
                        },
                    },
                }

            if "update" in lower or "edit" in lower or "change" in lower:

                if "deal" in lower:
                    return {
                        "tool": "hubspot_mcp_call",
                        "params": {
                            "tool_name": "crm_update_object",
                            "tool_params": {
                                "objectType": "deals",
                                "objectId":   extract_id(user_input),
                                "properties": {},
                            },
                        },
                    }

                if "company" in lower:
                    return {
                        "tool": "hubspot_mcp_call",
                        "params": {
                            "tool_name": "crm_update_object",
                            "tool_params": {
                                "objectType": "companies",
                                "objectId":   extract_id(user_input),
                                "properties": {},
                            },
                        },
                    }

                return {
                    "tool": "hubspot_mcp_call",
                    "params": {
                        "tool_name": "crm_update_object",
                        "tool_params": {
                            "objectType": "contacts",
                            "objectId":   extract_id(user_input),
                            "properties": {},
                        },
                    },
                }

            if "deal" in lower:
                return {
                    "tool": "hubspot_mcp_call",
                    "params": {
                        "tool_name": "crm_search_objects",
                        "tool_params": {
                            "objectType": "deals",
                            "query": user_input,
                            "limit": 5,
                        },
                    },
                }

            if "company" in lower or "companies" in lower:
                return {
                    "tool": "hubspot_mcp_call",
                    "params": {
                        "tool_name": "crm_search_objects",
                        "tool_params": {
                            "objectType": "companies",
                            "query": user_input,
                            "limit": 5,
                        },
                    },
                }

            if "ticket" in lower:
                return {
                    "tool": "hubspot_mcp_call",
                    "params": {
                        "tool_name": "crm_search_objects",
                        "tool_params": {
                            "objectType": "tickets",
                            "query": user_input,
                            "limit": 5,
                        },
                    },
                }

            if "quote" in lower:
                return {
                    "tool": "hubspot_mcp_call",
                    "params": {
                        "tool_name": "crm_search_objects",
                        "tool_params": {
                            "objectType": "quotes",
                            "query": user_input,
                            "limit": 5,
                        },
                    },
                }

            return {
                "tool": "hubspot_mcp_call",
                "params": {
                    "tool_name": "crm_search_objects",
                    "tool_params": {
                        "objectType": "contacts",
                        "query": user_input,
                        "limit": 5,
                    },
                },
            }

        if "create" in lower or "add" in lower:
            if "deal" in lower:
                return {
                    "tool": "hubspot_create_deal",
                    "params": {
                        "dealname": extract_value(user_input, "dealname") or extract_value(user_input, "deal") or "New Deal",
                        "amount": extract_value(user_input, "amount") or "0",
                        "hubspot_owner_id": "YOUR_OWNER_ID",
                    }
                }
            if "company" in lower or "companies" in lower:
                return {
                    "tool": "hubspot_create_company",
                    "params": {
                        "name": extract_value(user_input, "name") or extract_value(user_input, "company") or "New Company",
                        "domain": extract_value(user_input, "domain") or "",
                    }
                }
            if "ticket" in lower:
                return {
                    "tool": "hubspot_create_ticket",
                    "params": {
                        "subject": extract_value(user_input, "subject") or extract_value(user_input, "ticket") or "New Ticket",
                        "content": extract_value(user_input, "content") or "",
                    }
                }
            return {
                "tool": "hubspot_create_contact",
                "params": {
                    "email": extract_email(user_input),
                    "firstname": extract_value(user_input, "firstname"),
                    "lastname": extract_value(user_input, "lastname"),
                }
            }

        if "update" in lower or "edit" in lower or "change" in lower:
            if "deal" in lower:
                return {
                    "tool": "hubspot_update_deal",
                    "params": {
                        "deal_id": extract_id(user_input),
                        "dealname": extract_value(user_input, "dealname") or extract_value(user_input, "deal") or "",
                        "amount": extract_value(user_input, "amount") or "",
                    }
                }
            if "company" in lower or "companies" in lower:
                return {
                    "tool": "hubspot_update_company",
                    "params": {
                        "company_id": extract_id(user_input),
                        "name": extract_value(user_input, "name") or extract_value(user_input, "company") or "",
                        "domain": extract_value(user_input, "domain") or "",
                    }
                }
            if "ticket" in lower:
                return {
                    "tool": "hubspot_update_ticket",
                    "params": {
                        "ticket_id": extract_id(user_input),
                        "subject": extract_value(user_input, "subject") or extract_value(user_input, "ticket") or "",
                        "content": extract_value(user_input, "content") or "",
                    }
                }
            return {
                "tool": "hubspot_update_contact",
                "params": {
                    "contact_id": extract_id(user_input),
                    "email": extract_email(user_input),
                    "firstname": extract_value(user_input, "firstname"),
                    "lastname": extract_value(user_input, "lastname"),
                }
            }

        if "delete" in lower or "remove" in lower:
            if "deal" in lower:
                return {
                    "tool": "hubspot_delete_deal",
                    "params": {"deal_id": extract_id(user_input)}
                }
            if "company" in lower or "companies" in lower:
                return {
                    "tool": "hubspot_delete_company",
                    "params": {"company_id": extract_id(user_input)}
                }
            if "ticket" in lower:
                return {
                    "tool": "hubspot_delete_ticket",
                    "params": {"ticket_id": extract_id(user_input)}
                }
            
            return {
                "tool": "hubspot_delete_contact",
                "params": {"contact_id": extract_id(user_input)}
            }

        if "deal" in lower:
            return {"tool": "hubspot_get_deals", "params": {"limit": 5}}
        if "company" in lower or "companies" in lower:
            return {"tool": "hubspot_get_companies", "params": {"limit": 5}}
        if "ticket" in lower:
            return {"tool": "hubspot_get_tickets", "params": {"limit": 5}}
        return {"tool": "hubspot_get_contacts", "params": {"limit": 5}}

    if "list mcp tools" in lower or "available tools" in lower:
        if HUBSPOT_MCP_MODE == "beta":
            return {"tool": "hubspot_mcp_list_tools", "params": {}}

    if "search" in lower:
        return {"tool": "web_search_mcp", "params": {"query": user_input}}

    return None


def extract_email(text: str) -> str:
    """Extract email address from user message."""
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return match.group(0) if match else ""


def extract_id(text: str) -> str:
    """Extract a numeric ID from user message."""
    import re
    match = re.search(r'\b\d{6,}\b', text)
    return match.group(0) if match else ""


def extract_value(text: str, field: str) -> str:
    """
    Very basic extractor — returns the word after the field keyword.
    e.g. 'create deal SummerPromo' → 'SummerPromo'
    In production replace with an LLM extraction call.
    """
    pattern = rf'\b{field}[:=\s]+([A-Za-z0-9@._\-]+)'
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else ""