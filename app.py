from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from typing import Dict, List
import os, uuid, shutil
import uvicorn

app = FastAPI()

# ====== FOLDER UPLOAD ======
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ====== MODEL KLIEN & ROOM MANAGER ======
class Client:
    def __init__(self, username: str, ws: WebSocket):
        self.username = username
        self.ws = ws

class ConnectionManager:
    def __init__(self):
        # room_name -> list[Client]
        self.rooms: Dict[str, List[Client]] = {}

    def _get_clients(self, room: str) -> List[Client]:
        return self.rooms.get(room, [])

    def _get_usernames(self, room: str):
        return [c.username for c in self._get_clients(room)]

    async def connect(self, room: str, username: str, ws: WebSocket):
        await ws.accept()
        clients = self.rooms.setdefault(room, [])
        clients.append(Client(username, ws))
        print(f"[JOIN] {username} JOIN room '{room}' | total={len(clients)}")
        await self.broadcast_userlist(room)
        await self.broadcast(room, {
            "type": "system",
            "message": f"{username} bergabung ke grup",
            "time": datetime.utcnow().isoformat(),
        })

    async def disconnect(self, room: str, username: str, ws: WebSocket):
        clients = self.rooms.get(room, [])
        before = len(clients)
        clients = [c for c in clients if c.ws is not ws]
        if clients:
            self.rooms[room] = clients
        else:
            self.rooms.pop(room, None)
        after = len(clients)
        print(f"[LEAVE] {username} LEAVE room '{room}' | {before}→{after}")
        await self.broadcast(room, {
            "type": "system",
            "message": f"{username} keluar dari grup",
            "time": datetime.utcnow().isoformat(),
        })
        await self.broadcast_userlist(room)

    async def broadcast(self, room: str, message: dict):
        clients = self._get_clients(room)
        dead: List[Client] = []
        for c in clients:
            try:
                await c.ws.send_json(message)
            except Exception as e:
                print(f"[ERROR] kirim ke {c.username} gagal: {e}")
                dead.append(c)
        # bersihkan client mati
        if dead:
            self.rooms[room] = [c for c in clients if c not in dead]
            print(f"[CLEANUP] remove {len(dead)} client mati di room '{room}'")

    async def broadcast_userlist(self, room: str):
        users = self._get_usernames(room)
        print(f"[USERLIST] room '{room}': {users}")
        await self.broadcast(room, {
            "type": "userlist",
            "users": users,
        })

manager = ConnectionManager()

# ====== ENDPOINT WEBSOCKET ======
@app.websocket("/ws/{room}/{username}")
async def ws_endpoint(ws: WebSocket, room: str, username: str):
    await manager.connect(room, username, ws)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            if msg_type == "chat":
                text = (data.get("message") or "").strip()
                if not text:
                    continue
                print(f"[CHAT] room='{room}' user='{username}': {text}")
                await manager.broadcast(room, {
                    "type": "chat",
                    "username": username,
                    "message": text,
                    "time": datetime.utcnow().isoformat(),
                })
            elif msg_type == "file":
                print(f"[FILE] room='{room}' user='{username}' -> {data.get('filename')}")
                await manager.broadcast(room, {
                    "type": "file",
                    "username": username,
                    "url": data.get("url"),
                    "filename": data.get("filename"),
                    "mimetype": data.get("mimetype"),
                    "time": datetime.utcnow().isoformat(),
                })
    except WebSocketDisconnect:
        await manager.disconnect(room, username, ws)
    except Exception as e:
        print(f"[ERROR] WS room='{room}' user='{username}': {e}")
        await manager.disconnect(room, username, ws)

# ====== UPLOAD FILE ======
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1]
    unique = f"{uuid.uuid4().hex}{ext}"
    dst = os.path.join(UPLOAD_DIR, unique)
    with open(dst, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    print(f"[UPLOAD] {file.filename} -> {unique} ({file.content_type})")
    return {
        "filename": file.filename,
        "url": f"/uploads/{unique}",
        "mimetype": file.content_type,
    }

# ====== UI (INLINE HTML + CSS + JS) ======
@app.get("/")
async def home():
    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
      <meta charset="UTF-8" />
      <title>Cuppa-Chat</title>
      <style>
      :root{
        --brown-dark:#3b2f2f;--brown-main:#5b4636;--brown-light:#d9c3a3;
        --brown-bg:#f5ede2;--accent:#f2b26b;--bubble-me:#f2b26b;--bubble-other:#ffffff;
      }
      *{box-sizing:border-box;margin:0;padding:0}
      body{
        font-family:system-ui,-apple-system,Segoe UI,sans-serif;
        background:radial-gradient(circle,#f3e3cf,#c6a07a,#5b4636);
        height:100vh;display:flex;align-items:center;justify-content:center;
      }
      .app{
        width:95vw;max-width:1150px;height:90vh;
        display:grid;grid-template-columns:300px 1fr;
        background:#fff8ec;border-radius:22px;overflow:hidden;
        box-shadow:0 20px 40px rgba(0,0,0,.4);
      }
      .sidebar{
        background:linear-gradient(180deg,#3b2f2f,#4a3629);
        color:#fff;padding:18px;display:flex;flex-direction:column;gap:14px;
      }
      .logo{font-size:20px;font-weight:700;margin-bottom:4px}
      .join{
        background:rgba(0,0,0,.3);border-radius:14px;padding:12px;display:flex;flex-direction:column;gap:4px;
      }
      .join label{font-size:12px;opacity:.8}
      .join input{
        border:none;border-radius:8px;padding:6px 8px;margin-bottom:4px;
      }
      .join button{
        border:none;border-radius:9px;padding:7px 10px;margin-top:2px;
        background:#f2b26b;color:#3b2f2f;font-weight:700;cursor:pointer;
      }
      .join small{font-size:10px;opacity:.8;margin-top:4px;display:block}
      .sidebar h4{font-size:13px;margin-top:6px}
      #users{list-style:none;margin-top:4px;font-size:12px;max-height:200px;overflow:auto}
      #users li{padding:3px 5px;border-radius:6px;background:rgba(0,0,0,.25);margin-bottom:2px}
      .chat{display:flex;flex-direction:column;background:var(--brown-bg);}
      .chat-header{
        padding:10px 14px;background:linear-gradient(90deg,#5b4636,#7b5a40);
        color:#fff;display:flex;justify-content:space-between;align-items:center;font-size:13px;
      }
      .status-dot{width:10px;height:10px;border-radius:999px;background:#999;box-shadow:0 0 8px #999;}
      .status-dot.online{background:#4ade80;box-shadow:0 0 10px #4ade80;}
      .messages{
        flex:1;overflow:auto;padding:10px;
        background:repeating-linear-gradient(135deg,#f7ebdc,#f7ebdc 18px,#f3e2cf 18px,#f3e2cf 36px);
      }
      .msg-row{margin-bottom:8px;max-width:70%;}
      .msg-row.me{margin-left:auto;text-align:right;}
      .msg-row.other{margin-right:auto;text-align:left;}
      .bubble{
        display:inline-block;padding:7px 9px;border-radius:11px;
        background:var(--bubble-other);font-size:13px;
      }
      .msg-row.me .bubble{background:var(--bubble-me);}
      .sender{font-size:11px;font-weight:600;margin-bottom:1px;}
      .time{font-size:10px;opacity:.7;margin-top:2px;}
      .system{font-size:11px;text-align:center;margin:6px 0;color:#444;}
      .system span{background:rgba(0,0,0,.05);padding:3px 8px;border-radius:999px;}
      .bottom{
        padding:8px;display:flex;gap:6px;align-items:center;background:#f0e0cc;
      }
      .bottom input[type="text"]{
        flex:1;border:none;border-radius:16px;padding:7px 10px;font-size:13px;
      }
      .bottom button{
        border:none;border-radius:12px;padding:7px 12px;background:#5b4636;color:#fff;cursor:pointer;font-size:13px;
      }
      .bottom input[type="file"]{font-size:11px;}
      video,img{max-width:220px;border-radius:10px;margin-top:4px;}
      a.file-link{font-size:12px;color:#1f2937;text-decoration:none;}
      a.file-link:hover{text-decoration:underline;}
      @media(max-width:900px){
        .app{grid-template-columns:1fr;height:100vh;}
        .sidebar{flex-direction:row;flex-wrap:wrap;gap:8px;height:auto;}
        .join{flex:1 1 48%;}
      }
      </style>
    </head>
    <body>
      <div class="app">
        <div class="sidebar">
          <div class="logo">Cuppa-Chat</div>
          <div class="join">
            <label>Username</label>
            <input id="user" placeholder="Nama kamu">
            <label>Grup</label>
            <input id="room" placeholder="Contoh: ComaCode">
            <button id="join">Join</button>
            <small>Masukkan IP dan nama grup yang sama</small>
          </div>
          <h4>Online:</h4>
          <ul id="users"></ul>
        </div>
        <div class="chat">
          <div class="chat-header">
            <div>
              <div id="roomTitle">Belum terhubung</div>
              <div id="userTitle" style="font-size:11px;opacity:.9;">Isi username & grup, lalu tekan Join</div>
            </div>
            <div class="status-dot" id="statusDot"></div>
          </div>
          <div class="messages" id="messages"></div>
          <div class="bottom">
            <input type="file" id="file">
            <input type="text" id="msg" placeholder="Ketik pesan..." disabled>
            <button id="send" disabled>Kirim</button>
          </div>
        </div>
      </div>
      <script>
      const u=document.getElementById('user');
      const r=document.getElementById('room');
      const joinBtn=document.getElementById('join');
      const usersEl=document.getElementById('users');
      const msgs=document.getElementById('messages');
      const msgInput=document.getElementById('msg');
      const sendBtn=document.getElementById('send');
      const fileInput=document.getElementById('file');
      const roomTitle=document.getElementById('roomTitle');
      const userTitle=document.getElementById('userTitle');
      const statusDot=document.getElementById('statusDot');

      let ws=null,myUser=null,myRoom=null;

      function addSystem(text){
        const t=new Date().toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit'});
        msgs.insertAdjacentHTML('beforeend',"<div class='system'><span>"+text+" • "+t+"</span></div>");
        msgs.scrollTop=msgs.scrollHeight;
      }
      function addChat(username,message,timeISO){
        const self=username===myUser;
        const t=new Date(timeISO).toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit'});
        const cls=self?'me':'other';
        const html="<div class='msg-row "+cls+"'>"
          +"<div class='sender'>"+username+"</div>"
          +"<div class='bubble'>"+message+"</div>"
          +"<div class='time'>"+t+"</div>"
          +"</div>";
        msgs.insertAdjacentHTML('beforeend',html);
        msgs.scrollTop=msgs.scrollHeight;
      }
      function addFile(username,data){
        const self=username===myUser;
        const t=new Date(data.time).toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit'});
        const cls=self?'me':'other';
        let body="";
        if(data.mimetype && data.mimetype.startsWith("image/")){
          body+="<img src='"+data.url+"'>";
        }else if(data.mimetype && data.mimetype.startsWith("video/")){
          body+="<video src='"+data.url+"' controls></video>";
        }
        body+="<br><a class='file-link' href='"+data.url+"' target='_blank'>"+data.filename+"</a>";
        const html="<div class='msg-row "+cls+"'>"
          +"<div class='sender'>"+username+"</div>"
          +"<div class='bubble'>"+body+"</div>"
          +"<div class='time'>"+t+"</div>"
          +"</div>";
        msgs.insertAdjacentHTML('beforeend',html);
        msgs.scrollTop=msgs.scrollHeight;
      }
      function setOnlineState(on){
        if(on) statusDot.classList.add('online');
        else statusDot.classList.remove('online');
      }
      function isConnected(){
        return ws && ws.readyState===WebSocket.OPEN;
      }

      function connectWS(){
        const proto=location.protocol==='https:'?'wss':'ws';
        const url=proto+'://'+location.host+'/ws/'+encodeURIComponent(myRoom)+'/'+encodeURIComponent(myUser);
        ws=new WebSocket(url);
        console.log('[WS] connect',url);

        ws.onopen=()=>{
          console.log('[WS] open');
          setOnlineState(true);
          msgInput.disabled=false;
          sendBtn.disabled=false;
          addSystem('Terhubung ke server');
        };
        ws.onclose=()=>{
          console.log('[WS] close');
          setOnlineState(false);
          msgInput.disabled=true;
          sendBtn.disabled=true;
          addSystem('Koneksi terputus');
        };
        ws.onerror=(e)=>{
          console.log('[WS] error',e);
        };
        ws.onmessage=(ev)=>{
          let d;
          try{d=JSON.parse(ev.data);}catch{console.log('invalid',ev.data);return;}
          if(d.type==='system'){
            addSystem(d.message);
          }else if(d.type==='chat'){
            addChat(d.username,d.message,d.time);
          }else if(d.type==='file'){
            addFile(d.username,d);
          }else if(d.type==='userlist'){
            usersEl.innerHTML=(d.users||[]).map(x=>"<li>"+x+"</li>").join('');
          }
        };
      }

      joinBtn.onclick=()=>{
        if(!u.value.trim() || !r.value.trim()){
          alert('Isi username dan nama grup dulu.');
          return;
        }
        myUser=u.value.trim();
        myRoom=r.value.trim();
        roomTitle.textContent=myRoom;
        userTitle.textContent='Kamu masuk sebagai '+myUser;
        msgs.innerHTML='';
        addSystem('Menghubungkan ke grup "'+myRoom+'" ...');

        if(ws){try{ws.close();}catch(e){} ws=null;}
        connectWS();
      };

      sendBtn.onclick=()=>{
        if(!isConnected()){alert('Belum terhubung ke server.');return;}
        const text=msgInput.value.trim();
        if(!text)return;
        ws.send(JSON.stringify({type:'chat',message:text}));
        msgInput.value='';
      };

      msgInput.addEventListener('keydown',e=>{
        if(e.key==='Enter' && !e.shiftKey){
          e.preventDefault();
          sendBtn.click();
        }
      });

      fileInput.onchange=async()=>{
        const f=fileInput.files[0];
        if(!f)return;
        if(!isConnected()){
          alert('Belum terhubung ke server.');
          fileInput.value='';
          return;
        }
        const fd=new FormData();
        fd.append('file',f);
        try{
          const res=await fetch('/upload',{method:'POST',body:fd});
          const data=await res.json();
          ws.send(JSON.stringify({
            type:'file',
            url:data.url,
            filename:data.filename,
            mimetype:data.mimetype
          }));
        }catch(e){
          console.log('upload error',e);
          alert('Upload gagal.');
        }finally{
          fileInput.value='';
        }
      };
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)