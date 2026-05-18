import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket
from datetime import datetime
 
class ConnectionManager:

    def __init__(self):
        self.active_connections:Dict[str,WebSocket]={}
        self.conversation_rooms:Dict[int,set[str]]={}

    async def connect(self,client_id:str,websocket:WebSocket):
        await websocket.accept()
        self.active_connections[client_id]=websocket

    def disconnect(self,client_id:str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

        for room_client in self.conversation_rooms.values():
            room_client.discard(client_id)

    async def send_to_client(self, client_id: str, data: dict):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(data)
            except Exception:
                self.disconnect(client_id)

    async def broadcast(self, data: dict, exclude: str = None):
        dead = []
        for cid, ws in self.active_connections.items():
            if cid == exclude:
                continue
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)
 
    def join_room(self, client_id: str, conversation_id: int):
        if conversation_id not in self.conversation_rooms:
            self.conversation_rooms[conversation_id] = set()
        self.conversation_rooms[conversation_id].add(client_id)
 
    async def broadcast_to_room(self, conversation_id: int, data: dict, exclude: str = None):
        if conversation_id not in self.conversation_rooms:
            return
        clients = list(self.conversation_rooms[conversation_id])
        for cid in clients:
            if cid != exclude:
                await self.send_to_client(cid, data)
 
    def get_connection_count(self) -> int:
        return len(self.active_connections)
 
    def get_stats(self) -> dict:
        return {
            "active_connections": len(self.active_connections),
            "rooms": len(self.conversation_rooms),
            "client_ids": list(self.active_connections.keys()),
        }
 
 
ws_manager = ConnectionManager()